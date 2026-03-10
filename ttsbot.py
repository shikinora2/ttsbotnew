import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import os
import uuid
import re
from gtts import gTTS
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------
# 1. CẤU HÌNH CƠ BẢN
# ---------------------------------------------------------
MAX_TEXT_LENGTH = 150  # Giới hạn ký tự để VPS không bị quá tải (OOM)

DISCORD_TOKEN  = os.getenv("DISCORD_TOKEN")
DISCORD_APP_ID = os.getenv("DISCORD_APP_ID")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    application_id=int(DISCORD_APP_ID) if DISCORD_APP_ID else discord.utils.MISSING
)

# Khóa luồng (Lock) để đảm bảo tại 1 thời điểm chỉ có 1 tiến trình gen audio
tts_lock = asyncio.Lock()

# Quản lý trạng thái của từng Server (Guild)
class GuildState:
    def __init__(self):
        self.setup_channel_id = None
        self.queue = asyncio.Queue()
        self.play_task = None

guild_states = {}

def get_state(guild_id):
    if guild_id not in guild_states:
        guild_states[guild_id] = GuildState()
    return guild_states[guild_id]

# ---------------------------------------------------------
# 2. XỬ LÝ VĂN BẢN VÀ SINH ÂM THANH
# ---------------------------------------------------------
def clean_text(text):
    """Xóa link, tag người dùng, emoji để tránh bot đọc những thứ vô nghĩa"""
    text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
    text = re.sub(r'<@!?\d+>', '', text)   # Xóa tag @user
    text = re.sub(r'<:\w+:\d+>', '', text)  # Xóa custom emoji
    return text.strip()

def generate_audio_sync(text, filepath):
    """Hàm đồng bộ sinh âm thanh bằng gTTS (tiếng Việt)"""
    tts_obj = gTTS(text=text, lang='vi')
    tts_obj.save(filepath)

async def tts_worker(voice_client, state):
    """Tiến trình ngầm chạy liên tục để kiểm tra hàng đợi và phát âm thanh"""
    while True:
        filepath = None
        try:
            text = await state.queue.get()

            if not text:
                state.queue.task_done()
                continue

            # Dừng nếu bot đã bị ngắt kết nối
            if not voice_client.is_connected():
                state.queue.task_done()
                break

            filepath = f"temp_audio_{uuid.uuid4().hex}.mp3"

            async with tts_lock:
                await asyncio.to_thread(generate_audio_sync, text, filepath)

            # Kiểm tra lại sau khi sinh audio (bot có thể bị kick trong lúc chờ)
            if not voice_client.is_connected():
                state.queue.task_done()
                break

            while voice_client.is_playing():
                await asyncio.sleep(0.5)

            if os.path.exists(filepath):
                audio_source = discord.FFmpegPCMAudio(filepath)
                voice_client.play(audio_source)

                while voice_client.is_playing():
                    await asyncio.sleep(0.1)

            state.queue.task_done()

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[Lỗi Playback] {e}")
            try:
                state.queue.task_done()
            except Exception:
                pass
        finally:
            # Luôn dọn file tạm dù thành công hay lỗi
            if filepath and os.path.exists(filepath):
                os.remove(filepath)

# ---------------------------------------------------------
# 3. SLASH COMMANDS
# ---------------------------------------------------------
@bot.event
async def on_ready():
    await bot.tree.sync()
    user = bot.user
    print(f"Đã đăng nhập thành công: {user.name if user else 'unknown'}")
    print("Slash commands đã được đồng bộ.")
    await bot.change_presence(activity=discord.Game(name="/join | /leave | /help"))


@bot.tree.command(name="join", description="Bot vào kênh thoại bạn đang đứng và đọc tin nhắn từ kênh này")
@app_commands.guild_only()
async def slash_join(interaction: discord.Interaction):
    guild: discord.Guild = interaction.guild  # type: ignore[assignment]
    member: discord.Member = interaction.user  # type: ignore[assignment]
    channel: discord.TextChannel = interaction.channel  # type: ignore[assignment]
    state = get_state(guild.id)

    if member.voice is None:
        await interaction.response.send_message(
            "⚠️ Bạn phải vào một kênh thoại (Voice Channel) trước!", ephemeral=True
        )
        return

    voice_channel: discord.VoiceChannel = member.voice.channel  # type: ignore[assignment]

    # Chặn cướp bot: nếu bot đang hoạt động, chỉ người trong cùng voice channel mới được điều khiển
    if guild.voice_client is not None and state.setup_channel_id is not None:
        current_vc: discord.VoiceClient = guild.voice_client  # type: ignore[assignment]
        if voice_channel.id != current_vc.channel.id:  # type: ignore[union-attr]
            await interaction.response.send_message(
                f"⛔ Bot đang bận phục vụ kênh **{current_vc.channel.name}**.\n"  # type: ignore[union-attr]
                f"Vào kênh đó hoặc dùng `/leave` để giải phóng bot trước.",
                ephemeral=True
            )
            return

    if guild.voice_client is not None:
        vc: discord.VoiceClient = guild.voice_client  # type: ignore[assignment]
        await vc.move_to(voice_channel)
    else:
        vc = await voice_channel.connect()  # type: ignore[assignment]

    # Hủy task cũ (kể cả khi bot bị kick trước đó mà task vẫn còn zombie)
    if state.play_task and not state.play_task.done():
        state.play_task.cancel()
        try:
            await state.play_task
        except asyncio.CancelledError:
            pass
    state.play_task = None

    # Xóa queue cũ để không đọc tin nhắn từ kênh/session trước
    state.queue = asyncio.Queue()

    # Cập nhật kênh chat TTS = kênh nơi user gõ /join
    state.setup_channel_id = channel.id

    # Tạo worker mới với voice_client hiện tại
    state.play_task = bot.loop.create_task(tts_worker(vc, state))

    await interaction.response.send_message(
        f"👋 Đã tham gia **{voice_channel.name}**.\n"
        f"📢 Đang lắng nghe kênh **{channel.name}** — hãy chat để bot đọc!"
    )


@bot.tree.command(name="leave", description="Bot rời kênh thoại và xóa hàng đợi")
@app_commands.guild_only()
async def slash_leave(interaction: discord.Interaction):
    guild: discord.Guild = interaction.guild  # type: ignore[assignment]
    state = get_state(guild.id)

    if guild.voice_client:
        vc: discord.VoiceClient = guild.voice_client  # type: ignore[assignment]
        if state.play_task and not state.play_task.done():
            state.play_task.cancel()
            try:
                await state.play_task
            except asyncio.CancelledError:
                pass
        state.play_task = None

        state.queue = asyncio.Queue()
        state.setup_channel_id = None

        await vc.disconnect(force=False)
        await interaction.response.send_message("🛑 Đã rời kênh thoại và xóa hàng đợi.")
    else:
        await interaction.response.send_message(
            "Bot đang không ở trong kênh thoại nào.", ephemeral=True
        )


@bot.tree.command(name="help", description="Hiển thị danh sách lệnh của bot")
@app_commands.guild_only()
async def slash_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 Hướng dẫn dùng TTS Bot",
        description="Bot đọc tin nhắn chat thành giọng nói tiếng Việt (Google TTS)",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="/join",
        value="Bot vào kênh thoại bạn đang đứng.\nKênh chat nơi bạn gõ lệnh sẽ được lắng nghe để đọc TTS.",
        inline=False
    )
    embed.add_field(
        name="/leave",
        value="Bot rời kênh thoại và xóa toàn bộ hàng đợi.",
        inline=False
    )
    embed.add_field(
        name="/help",
        value="Hiển thị tin nhắn hướng dẫn này.",
        inline=False
    )
    embed.set_footer(text=f"Giới hạn độ dài tin nhắn: {MAX_TEXT_LENGTH} ký tự")
    await interaction.response.send_message(embed=embed)


# ---------------------------------------------------------
# 4. XỬ LÝ KHI CÓ THAY ĐỔI TRẠNG THÁI VOICE
# ---------------------------------------------------------
@bot.event
async def on_voice_state_update(member, before, after):
    if bot.user is None:
        return

    # --- Trường hợp 1: chính bot bị kick / disconnect ngoài /leave ---
    if member.id == bot.user.id:
        if before.channel is not None and after.channel is None:
            guild_id = before.channel.guild.id
            state = get_state(guild_id)
            if state.play_task and not state.play_task.done():
                state.play_task.cancel()
            state.play_task = None
            state.queue = asyncio.Queue()
            state.setup_channel_id = None
            print(f"[Info] Bot bị ngắt khỏi voice — đã reset state guild {guild_id}")
        return

    # --- Trường hợp 2: một thành viên rời kênh mà bot đang ở ---
    guild = before.channel.guild if before.channel else None
    if guild is None:
        return

    vc = guild.voice_client
    if vc is None:
        return

    bot_channel = vc.channel
    # Kiểm tra xem người vừa rời có ở kênh bot đang đứng không
    if before.channel != bot_channel:
        return

    # Đếm số thành viên thật (không tính bot) còn lại trong kênh
    human_members = [m for m in bot_channel.members if not m.bot]
    if len(human_members) == 0:
        state = get_state(guild.id)
        # Thông báo vào kênh chat đã setup (nếu còn)
        if state.setup_channel_id:
            ch = guild.get_channel(state.setup_channel_id)
            if ch:
                await ch.send("👋 Kênh thoại trống — bot tự rời để tiết kiệm tài nguyên.")  # type: ignore[union-attr]

        if state.play_task and not state.play_task.done():
            state.play_task.cancel()
            try:
                await state.play_task
            except asyncio.CancelledError:
                pass
        state.play_task = None
        state.queue = asyncio.Queue()
        state.setup_channel_id = None

        await vc.disconnect(force=False)  # type: ignore[union-attr]
        print(f"[Info] Kênh trống — bot tự rời guild {guild.id}")


# ---------------------------------------------------------
# 5. LẮNG NGHE TIN NHẮN (MESSAGE EVENT)
# ---------------------------------------------------------
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if not message.guild:
        return

    state = get_state(message.guild.id)

    if message.channel.id == state.setup_channel_id and message.guild.voice_client:
        text = clean_text(message.content)

        if len(text) > MAX_TEXT_LENGTH:
            await message.channel.send(
                f"⚠️ Tin nhắn quá dài (> {MAX_TEXT_LENGTH} ký tự). Bot sẽ không đọc để tránh kẹt mạng."
            )
            return

        if text:
            await state.queue.put(text)
            await message.add_reaction("👀")

# ---------------------------------------------------------
# CHẠY BOT
# ---------------------------------------------------------
if __name__ == "__main__":
    if not DISCORD_TOKEN or DISCORD_TOKEN == "ĐIỀN_TOKEN_VÀO_ĐÂY":
        raise SystemExit("[LỖI] Chưa điền DISCORD_TOKEN vào file .env")
    if not DISCORD_APP_ID or DISCORD_APP_ID == "ĐIỀN_APP_ID_VÀO_ĐÂY":
        raise SystemExit("[LỖI] Chưa điền DISCORD_APP_ID vào file .env")
    bot.run(DISCORD_TOKEN)