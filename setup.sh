#!/bin/bash
# ==============================================================
# setup.sh - Deploy 3 TTS Bots tren VPS (Ubuntu/Debian)
# Chay: bash setup.sh
# ==============================================================

set -e

BOT_COUNT=3

echo ""
echo "=========================================================="
echo "  TTS Bot - Cai dat $BOT_COUNT bot tren VPS"
echo "=========================================================="

# ----------------------------------------------------------
# 1. Cap nhat he thong & cai cac goi can thiet
# ----------------------------------------------------------
echo ""
echo "[1/5] Cap nhat he thong..."
sudo apt-get update -y
sudo apt-get upgrade -y

echo "[1/5] Cai Python3, pip, ffmpeg..."
sudo apt-get install -y python3 python3-pip python3-venv ffmpeg

# ----------------------------------------------------------
# 2. Tao virtual environment dung chung cho ca 3 bot
# ----------------------------------------------------------
echo ""
echo "[2/5] Tao virtual environment dung chung..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "  -> Da tao venv/"
else
    echo "  -> venv/ da ton tai, bo qua."
fi
source venv/bin/activate

# ----------------------------------------------------------
# 3. Cai cac thu vien Python
# ----------------------------------------------------------
echo ""
echo "[3/5] Cai thu vien Python (discord.py, gTTS, python-dotenv)..."
pip install --upgrade pip
pip install "discord.py[voice]" gTTS python-dotenv
pip freeze > requirements.txt
echo "  -> Da luu requirements.txt"

# ----------------------------------------------------------
# 4. Tao file .env cho tung bot neu chua co
# ----------------------------------------------------------
echo ""
echo "[4/5] Kiem tra file .env cua tung bot..."

for i in $(seq 1 $BOT_COUNT); do
    ENV_FILE=".env.bot${i}"
    if [ ! -f "$ENV_FILE" ]; then
        cat > "$ENV_FILE" <<EOF
# Bot $i - Dien thong tin cua bot $i vao day
DISCORD_TOKEN=DIEN_TOKEN_BOT${i}_VAO_DAY
DISCORD_APP_ID=DIEN_APP_ID_BOT${i}_VAO_DAY
EOF
        echo "  -> Da tao $ENV_FILE (chua dien token)"
    else
        echo "  -> $ENV_FILE da ton tai, giu nguyen."
    fi
done

# ----------------------------------------------------------
# 5. Tao 3 systemd service doc lap
# ----------------------------------------------------------
echo ""
echo "[5/5] Cai dat $BOT_COUNT systemd service..."

WORK_DIR="$(pwd)"
VENV_PYTHON="$WORK_DIR/venv/bin/python"
USER_NAME="$(whoami)"

for i in $(seq 1 $BOT_COUNT); do
    SERVICE_NAME="ttsbot${i}.service"
    ENV_FILE="$WORK_DIR/.env.bot${i}"

    sudo tee /etc/systemd/system/$SERVICE_NAME > /dev/null <<EOF
[Unit]
Description=TTS Discord Bot $i
After=network.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$WORK_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$VENV_PYTHON $WORK_DIR/ttsbot.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable $SERVICE_NAME
    echo "  -> $SERVICE_NAME da dang ky va bat auto-start."
done

# ----------------------------------------------------------
# Huong dan tiep theo
# ----------------------------------------------------------
echo ""
echo "=========================================================="
echo "  HOAN TAT - 3 BOT SAN SANG!"
echo "=========================================================="
echo ""
echo "  BUOC TIEP THEO:"
echo ""
echo "  1. Dien token cho tung bot:"
echo "       nano .env.bot1   # Bot 1"
echo "       nano .env.bot2   # Bot 2"
echo "       nano .env.bot3   # Bot 3"
echo ""
echo "  2. Khoi dong tat ca 3 bot:"
echo "       sudo systemctl start ttsbot1 ttsbot2 ttsbot3"
echo ""
echo "  3. Xem log tung bot:"
echo "       sudo journalctl -u ttsbot1 -f"
echo "       sudo journalctl -u ttsbot2 -f"
echo "       sudo journalctl -u ttsbot3 -f"
echo ""
echo "  4. Dung/restart tung con doc lap:"
echo "       sudo systemctl stop ttsbot2"
echo "       sudo systemctl restart ttsbot3"
echo ""
echo "  5. Cap nhat code (1 lan cho ca 3 bot):"
echo "       git pull && sudo systemctl restart ttsbot1 ttsbot2 ttsbot3"
echo ""