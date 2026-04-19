# 🚀 Hướng Dẫn Deploy Miễn Phí — Fraud Detection System

Tài liệu này hướng dẫn 3 phương án deploy **miễn phí** để demo đồ án cho thầy.

---

## ⚡ Phương Án 1: Ngrok Tunnel (Đơn Giản Nhất — Khuyến Nghị)

**Cách hoạt động**: Chạy Docker trên laptop → expose port qua Internet bằng ngrok → thầy truy cập qua link.

### Bước 1: Cài đặt ngrok
```bash
# macOS
brew install ngrok

# Hoặc tải trực tiếp tại: https://ngrok.com/download
```

### Bước 2: Đăng ký tài khoản ngrok (miễn phí)
```bash
# Vào https://dashboard.ngrok.com/signup → lấy auth token
ngrok config add-authtoken <YOUR_TOKEN>
```

### Bước 3: Khởi động hệ thống
```bash
# Tạo demo data nhỏ (nếu chưa có paysim.csv)
python3 scripts/generate_demo_data.py

# Khởi động containers (demo mode — nhẹ RAM)
docker compose -f docker-compose.demo.yml up -d --build

# Đợi ~60 giây cho tất cả services khởi động

# Load blacklist vào Redis
docker compose -f docker-compose.demo.yml run --rm transaction_consumer \
  spark-submit scripts/blacklist_loader.py

# Train model
docker compose -f docker-compose.demo.yml run --rm transaction_consumer \
  spark-submit scripts/train_paysim_model.py
```

### Bước 4: Expose dashboard ra Internet
```bash
# Expose Streamlit dashboard
ngrok http 8501

# Output sẽ hiện link kiểu:
# https://abc123.ngrok-free.app → chuyển link này cho thầy
```

### Bước 5: Gửi link cho thầy
- 📊 **Dashboard**: `https://abc123.ngrok-free.app`
- Thầy truy cập link → thấy ngay dashboard realtime!

### Bước 6: Tắt sau khi demo xong
```bash
# Ctrl+C trên terminal ngrok
docker compose -f docker-compose.demo.yml down
```

---

## 🖥️ Phương Án 2: Oracle Cloud Free Tier (Deploy Thực Sự)

**Cách hoạt động**: Tạo VM miễn phí **vĩnh viễn** trên Oracle Cloud (ARM 4 CPU / 24GB RAM) → deploy Docker lên đó.

### Bước 1: Đăng ký Oracle Cloud
- Vào https://cloud.oracle.com/en_US/tryit
- Cần credit card để xác minh (nhưng **KHÔNG BỊ TRỪ TIỀN**)
- Chọn region Osaka hoặc Seoul (gần VN nhất)

### Bước 2: Tạo VM (Compute Instance)
- **Shape**: Ampere A1 Flex (ARM) — 4 OCPU, 24GB RAM (Always Free ✅)
- **OS**: Ubuntu 22.04 hoặc Oracle Linux 8
- **Storage**: 200GB boot volume (miễn phí)
- Tải SSH key khi tạo để SSH vào sau

### Bước 3: Cài Docker trên VM
```bash
# SSH vào VM
ssh -i <your-key.pem> ubuntu@<VM_PUBLIC_IP>

# Cài Docker
sudo apt update
sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker
```

### Bước 4: Clone và deploy
```bash
git clone https://github.com/Vantoan252003/BigDataFraudDetection.git
cd BigDataFraudDetection

# Tạo demo data 
python3 scripts/generate_demo_data.py

# Copy file .env (sửa password nếu muốn)
cp .env.example .env

# Deploy
docker compose -f docker-compose.demo.yml up -d --build
```

### Bước 5: Mở firewall
- Trong Oracle Cloud Console → Networking → Virtual Cloud Network → Security List
- Thêm Ingress Rule: `0.0.0.0/0` → Port `8501` (TCP)
- Trên VM: `sudo iptables -I INPUT -p tcp --dport 8501 -j ACCEPT`

### Bước 6: Truy cập
- `http://<VM_PUBLIC_IP>:8501`

---

## 🔧 Phương Án 3: GitHub Codespaces (Nhanh Nhất)

**Cách hoạt động**: GitHub cho miễn phí 60 giờ/tháng chạy VM trực tiếp từ repo.

### Bước 1: Mở Codespace
- Vào repo GitHub → Click nút **Code** → Tab **Codespaces** → **Create codespace on main**

### Bước 2: Chạy trong Codespace terminal
```bash
# Tạo demo data
python3 scripts/generate_demo_data.py

# Deploy
docker compose -f docker-compose.demo.yml up -d --build

# Đợi 60 giây
```

### Bước 3: Forward port
- Codespace tự động forward port 8501
- Click link `http://localhost:8501` → nó sẽ tạo public URL
- Hoặc vào tab **PORTS** → change visibility sang **Public**

### Lưu ý
- Free tier chỉ có **2 core / 8GB RAM** → hơi chậm nhưng đủ demo
- Giới hạn **60 giờ/tháng** — tắt ngay sau khi demo xong

---

## 📋 So Sánh 3 Phương Án

| | Ngrok | Oracle Cloud | GitHub Codespaces |
|---|---|---|---|
| **Độ khó** | ⭐ Dễ nhất | ⭐⭐⭐ Khó nhất | ⭐⭐ Trung bình |
| **RAM** | Dùng laptop | 24GB (free) | 8GB (free) |
| **Thời gian setup** | 5 phút | 30-60 phút | 10 phút |
| **Thời gian miễn phí** | Unlimited | Lifetime | 60h/tháng |
| **Cần laptop bật?** | ✅ Có | ❌ Không | ❌ Không |
| **Tốc độ** | Nhanh | Nhanh nhất | Chậm hơn |

### 🎯 Khuyến nghị: Dùng **Phương Án 1 (Ngrok)** nếu demo trực tiếp tại lớp!

---

## 🔑 Chú Ý Bảo Mật Khi Demo

1. **API Key**: Khi demo endpoint FastAPI, thêm header:
```bash
curl -X POST http://localhost:8000/blacklist-transaction \
  -H "X-API-Key: fd_key_2026_s3cur3_d3m0_k3y_x7q9"
```

2. **Dashboard**: Streamlit dashboard đã tự động mask account IDs (`C1234****`)

3. **Sau khi demo**: Tắt tất cả services
```bash
docker compose -f docker-compose.demo.yml down
# Nếu dùng ngrok: Ctrl+C
```
