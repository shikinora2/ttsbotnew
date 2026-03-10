#!/bin/bash
# ==============================================================
# setup.sh — Thiết lập TTS Bot trên VPS (Ubuntu/Debian)
# Chạy: bash setup.sh
# ==============================================================

set -e  # Dừng ngay nếu có lỗi

echo ""
echo "=========================================================="
echo "  TTS Bot — Bắt đầu cài đặt trên VPS"
echo "=========================================================="

# ----------------------------------------------------------
# 1. Cập nhật hệ thống & cài các gói cần thiết
# ----------------------------------------------------------
echo ""
echo "[1/6] Cập nhật hệ thống..."
sudo apt-get update -y
sudo apt-get upgrade -y

echo "[1/6] Cài Python3, pip, ffmpeg..."
sudo apt-get install -y python3 python3-pip python3-venv ffmpeg

# ----------------------------------------------------------
# 2. Tạo môi trường ảo Python
# ----------------------------------------------------------
echo ""
echo "[2/6] Tạo virtual environment..."
python3 -m venv venv
source venv/bin/activate

# ----------------------------------------------------------
# 3. Cài các thư viện Python
# ----------------------------------------------------------
echo ""
echo "[3/6] Cài thư viện Python (discord.py, gTTS, python-dotenv)..."
pip install --upgrade pip
pip install "discord.py[voice]" gTTS python-dotenv

# Lưu danh sách thư viện
pip freeze > requirements.txt
echo "  → Đã lưu requirements.txt"

# ----------------------------------------------------------
# 4. Kiểm tra file .env
# ----------------------------------------------------------
echo ""
echo "[4/6] Kiểm tra file .env..."
if [ ! -f ".env" ]; then
    echo "  [!] Chưa có file .env — tạo mẫu..."
    cat > .env <<'EOF'
# ============================================================
# Cấu hình Discord Bot — Điền thông tin của bạn vào đây
# ============================================================
DISCORD_TOKEN=ĐIỀN_TOKEN_VÀO_ĐÂY
DISCORD_APP_ID=ĐIỀN_APP_ID_VÀO_ĐÂY
EOF
    echo "  → Đã tạo .env — hãy điền DISCORD_TOKEN và DISCORD_APP_ID trước khi chạy bot!"
else
    echo "  → File .env đã tồn tại."
fi

# ----------------------------------------------------------
# 5. Tạo systemd service để bot chạy nền & tự khởi động
# ----------------------------------------------------------
echo ""
echo "[5/6] Cài đặt systemd service (ttsbot.service)..."

WORK_DIR="$(pwd)"
VENV_PYTHON="$WORK_DIR/venv/bin/python"
USER_NAME="$(whoami)"

sudo tee /etc/systemd/system/ttsbot.service > /dev/null <<EOF
[Unit]
Description=TTS Discord Bot
After=network.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$WORK_DIR
ExecStart=$VENV_PYTHON $WORK_DIR/ttsbot.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ttsbot.service
echo "  → Service ttsbot.service đã được đăng ký và bật auto-start."

# ----------------------------------------------------------
# 6. Hướng dẫn tiếp theo
# ----------------------------------------------------------
echo ""
echo "=========================================================="
echo "  HOÀN TẤT CÀI ĐẶT!"
echo "=========================================================="
echo ""
echo "  Bước tiếp theo:"
echo ""
echo "  1. Điền token vào file .env:"
echo "       nano .env"
echo ""
echo "  2. Khởi động bot:"
echo "       sudo systemctl start ttsbot"
echo ""
echo "  3. Xem log realtime:"
echo "       sudo journalctl -u ttsbot -f"
echo ""
echo "  4. Dừng bot:"
echo "       sudo systemctl stop ttsbot"
echo ""
echo "  5. Khởi động lại bot:"
echo "       sudo systemctl restart ttsbot"
echo ""
