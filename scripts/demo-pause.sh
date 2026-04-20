#!/bin/bash
# demo-pause.sh — Tạm dừng toàn bộ pipeline để bảo toàn dữ liệu demo
# Lưu ý: CHỈ dừng producer (ngưng stream data). Dashboard + DB vẫn chạy để xem lại data đã có.

echo "⏸️  Đang tạm dừng pipeline..."

cd ~/BigDataFraudDetection 2>/dev/null || cd "$(dirname "$0")/.."

# Dừng producer (ngừng gửi data mới vào Kafka)
sudo docker compose stop producer
echo "   ✅ Producer đã dừng — không còn data mới được gửi"

# Dừng consumer (ngừng xử lý data từ Kafka)
sudo docker compose stop transaction_consumer
echo "   ✅ Consumer đã dừng — không còn data mới được ghi vào DB"

# Dừng trainer (không cần train lại)
sudo docker compose stop trainer blacklist_loader
echo "   ✅ Trainer + Blacklist Loader đã dừng"

echo ""
echo "📊 CÁC SERVICE VẪN CHẠY:"
echo "   - Streamlit Dashboard (port 8501) — xem data đã có"
echo "   - FastAPI (port 8000) — API vẫn hoạt động"
echo "   - PostgreSQL — database vẫn lưu trữ"
echo "   - Redis — cache vẫn hoạt động"
echo "   - MLflow (port 5050) — xem model metrics"
echo ""
echo "🔄 Để tiếp tục demo: bash scripts/demo-resume.sh"
