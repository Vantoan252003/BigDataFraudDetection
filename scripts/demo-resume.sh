#!/bin/bash
# demo-resume.sh — Tiếp tục pipeline sau khi đã pause
# Producer sẽ tiếp tục stream từ đầu file PaySim

echo "▶️  Đang khởi động lại pipeline..."

cd ~/BigDataFraudDetection 2>/dev/null || cd "$(dirname "$0")/.."

# Khởi động lại producer + consumer
sudo docker compose start producer transaction_consumer trainer blacklist_loader

echo ""
echo "✅ Pipeline đã được khởi động lại!"
echo "   - Producer: đang stream data vào Kafka"  
echo "   - Consumer: đang xử lý và ghi vào PostgreSQL"
echo "   - Trainer: đang train model"
echo ""
echo "📊 Dashboard: http://$(curl -s ifconfig.me 2>/dev/null || echo 'YOUR_IP'):8501"
echo "⏸️  Để dừng lại: bash scripts/demo-pause.sh"
