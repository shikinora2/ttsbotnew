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
    application_id=int(DISCORD_APP_ID) if DISCORD_APP_ID else None
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
        try:
            text = await state.queue.get()

            if not text:
                state.queue.task_done()
                continue

            filepath = f"temp_audio_{uuid.uuid4().hex}.mp3"

            async with tts_lock:
                await asyncio.to_thread(generate_audio_sync, text, filepath)

            while voice_client.is_playing():
                await asyncio.sleep(0.5)

            if os.path.exists(filepath):
                audio_source = discord.FFmpegPCMAudio(filepath)
                voice_client.play(audio_source)

                while voice_client.is_playing():
                    await asyncio.sleep(0.1)

                if os.path.exists(filepath):
                    os.remove(filepath)

            state.queue.task_done()

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[Lỗi Playback] {e}")

# ---------------------------------------------------------
# 3. SLASH COMMANDS
# ---------------------------------------------------------
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Đã đăng nhập thành công: {bot.user.name}")
    print("Slash commands đã được đồng bộ.")
    await bot.change_presence(activity=discord.Game(name="/join | /leave | /help"))


@bot.tree.command(name="join", description="Bot vào kênh thoại bạn đang đứng và đọc tin nhắn từ kênh này")
async def slash_join(interaction: discord.Interaction):
    state = get_state(interaction.guild.id)

    if interaction.user.voice is None:
        await interaction.response.send_message(
            "⚠️ Bạn phải vào một kênh thoại (Voice Channel) trước!", ephemeral=True
        )
        return

    voice_channel = interaction.user.voice.channel

    if interaction.guild.voice_client is not None:
        await interaction.guild.voice_client.move_to(voice_channel)
        voice_client = interaction.guild.voice_client
    else:
        voice_client = await voice_channel.connect()

    # Kênh chat nơi user gõ /join chính là kênh TTS
    state.setup_channel_id = interaction.channel.id

    if state.play_task is None or state.play_task.done():
        state.play_task = bot.loop.create_task(tts_worker(voice_client, state))

    await interaction.response.send_message(
        f"👋 Đã tham gia **{voice_channel.name}**.\n"
        f"📢 Đang lắng nghe kênh **{interaction.channel.name}** — hãy chat để bot đọc!"
    )


@bot.tree.command(name="leave", description="Bot rời kênh thoại và xóa hàng đợi")
async def slash_leave(interaction: discord.Interaction):
    state = get_state(interaction.guild.id)

    if interaction.guild.voice_client:
        if state.play_task:
            state.play_task.cancel()
            state.play_task = None

        state.queue = asyncio.Queue()
        state.setup_channel_id = None

        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("🛑 Đã rời kênh thoại và xóa hàng đợi.")
    else:
        await interaction.response.send_message(
            "Bot đang không ở trong kênh thoại nào.", ephemeral=True
        )


@bot.tree.command(name="help", description="Hiển thị danh sách lệnh của bot")
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
# 4. LẮNG NGHE TIN NHẮN (MESSAGE EVENT)
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