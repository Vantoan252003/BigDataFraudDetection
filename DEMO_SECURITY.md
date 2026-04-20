# 🛡️ Hướng Dẫn Demo Bảo Mật - Fraud Detection System

## Tổng Quan Nhanh

Hệ thống có **12 tính năng bảo mật** được nâng cấp. Dưới đây là cách bạn trình bày/demo từng cái cho thầy.

---

## 1. 🔒 API Key Authentication (FastAPI)

**Ý nghĩa:** API không ai cũng có thể truy cập — phải có key mới được gửi giao dịch.

**Cách demo:** Mở terminal và thử 2 lệnh:

```bash
# ❌ KHÔNG có API Key → Bị từ chối 401
curl http://140.245.127.238:8000/health

# ✅ CÓ API Key → Được phép
curl -H "X-API-Key: fd_key_2026_s3cur3_d3m0_k3y_x7q9" http://140.245.127.238:8000/health
```

**Giải thích cho thầy:** "API được bảo vệ bằng API Key header. Nếu không có key hoặc key sai → server trả về 401 Unauthorized."

---

## 2. ⏱️ Rate Limiting (100 request/phút)

**Ý nghĩa:** Chống DDoS / brute-force — mỗi IP chỉ gọi được 100 request/phút.

**Cách demo:** Gửi nhiều request liên tục:

```bash
# Gửi 5 request nhanh — thấy header X-RateLimit-Remaining giảm dần
for i in {1..5}; do
  curl -s -o /dev/null -w "Request $i: HTTP %{http_code}\n" \
    -H "X-API-Key: fd_key_2026_s3cur3_d3m0_k3y_x7q9" \
    http://140.245.127.238:8000/health
done
```

**Giải thích:** "Hệ thống giới hạn 100 request/phút cho mỗi IP. Khi vượt quá → trả về 429 Too Many Requests."

---

## 3. 🛡️ SQL Injection Prevention

**Ý nghĩa:** Hacker không thể inject mã SQL qua ô tìm kiếm.

**Cách demo trên Dashboard (http://140.245.127.238:8501):**

1. Vào tab **Transaction Explorer**
2. Nhập vào ô "Tìm Account ID": `'; DROP TABLE shop.transactions; --`
3. Bấm Enter → **Không có kết quả**, bảng KHÔNG bị xóa!

**Giải thích:** "Trước đó, query dùng f-string trực tiếp (nguy hiểm). Giờ đã chuyển sang parameterized query với `text()` binding — SQL injection không thể xảy ra."

---

## 4. 🔐 PII Masking (Che thông tin cá nhân)

**Ý nghĩa:** Tài khoản người dùng không bị lộ trên dashboard.

**Cách demo:** Nhìn vào bất kỳ bảng nào trên Dashboard:
- Account ID hiển thị: `C1234****` (thay vì `C1234567890`)
- Cả `nameOrig` và `nameDest` đều bị mask

**Giải thích:** "Theo GDPR/PII best practice, dữ liệu nhạy cảm được che đi ở tầng hiển thị. Dữ liệu gốc vẫn nguyên trong database."

---

## 5. 🔑 Secrets Management (.env)

**Ý nghĩa:** Mật khẩu, API key không hardcode trong source code.

**Cách demo:** Mở file `.env.example` cho thầy xem:
```
POSTGRES_USER=fraud_user
POSTGRES_PASSWORD=<thay đổi ở đây>
REDIS_PASSWORD=<thay đổi ở đây>
FRAUD_API_KEY=<thay đổi ở đây>
```

**Giải thích:** "Tất cả credential được tách ra file `.env` (không push lên Git). Docker Compose dùng `env_file: .env` để inject biến môi trường."

---

## 6. 🔒 Redis Password Protection

**Ý nghĩa:** Redis (cache tốc độ cao cho blacklist) yêu cầu mật khẩu.

**Giải thích:** "Redis được cấu hình `--requirepass`. Tất cả service connect Redis đều phải cung cấp password. Điều này ngăn truy cập trái phép vào cache."

---

## 7. 📊 Health Check & Docker Hardening

**Ý nghĩa:** Container tự kiểm tra sức khỏe, tự restart khi lỗi.

**Cách demo:**
```bash
# Xem trạng thái tất cả container
docker compose ps

# Kết quả sẽ hiện (healthy) cho Kafka, PostgreSQL, Redis
```

**Giải thích:** "Mỗi service có health check riêng. Ví dụ PostgreSQL check `pg_isready`, Redis check `redis-cli ping`. Nếu service die → Docker tự restart (policy: `unless-stopped`)."

---

## 8. 🌐 CORS & Security Headers

**Ý nghĩa:** Chỉ Streamlit dashboard mới được gọi API, chặn các website khác.

**Cách demo:**
```bash
# Header bảo mật trả về trong mỗi response
curl -I -H "X-API-Key: fd_key_2026_s3cur3_d3m0_k3y_x7q9" \
  http://140.245.127.238:8000/health
```

Bạn sẽ thấy các header:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`

---

## 9. 📝 Audit Logging

**Ý nghĩa:** Mọi request đều được ghi log — ai, khi nào, endpoint nào, kết quả ra sao.

**Cách demo:**
```bash
# Xem log FastAPI
docker compose logs fastapi --tail 20
```

Log sẽ hiện: `2026-04-20 13:00:00 | INFO | IP=172.18.0.1 | POST /health | 200 | 5ms | key=fd_k***`

---

## 10. 🧹 Input Sanitization

**Ý nghĩa:** Đầu vào người dùng được lọc ký tự đặc biệt.

**Cách demo trên Dashboard:**
1. Vào Transaction Explorer
2. Nhập `<script>alert('XSS')</script>` vào ô tìm kiếm
3. Kết quả: Ký tự đặc biệt bị loại bỏ, chỉ giữ alphanumeric

---

## 11. 💾 PostgreSQL Hardening

**Ý nghĩa:** Database có schema, index, permissions đúng chuẩn.

**Giải thích:** "Schema `shop` được tạo tự động bởi init script. Có index trên `nameOrig`, `nameDest`, `ingested_at` để tăng tốc query. Table `audit_log` ghi lại mọi thay đổi."

---

## 12. 🧪 Security Tests (31 test cases)

**Ý nghĩa:** Test tự động kiểm chứng mọi lỗ hổng đã được vá.

**Cách demo (chạy ở local):**
```bash
pytest tests/test_security.py -v
```

Kết quả: **31 passed ✅**
- TestPIIMasking: 6 passed
- TestInputSanitization: 8 passed
- TestAmountValidation: 4 passed
- TestHashing: 5 passed
- TestSQLInjectionPatterns: 8 passed

---

## 🌐 Các Trang Web Có Thể Truy Cập

| URL | Mô tả | Yêu cầu |
|---|---|---|
| `http://140.245.127.238:8501` | **Dashboard Streamlit** — Trang chính | Không cần key |
| `http://140.245.127.238:8000/health` | **Health Check API** | Cần `X-API-Key` header |
| `http://140.245.127.238:8000/docs` | **Swagger UI** — Tài liệu API tự động | Cần `X-API-Key` để test |
| `http://140.245.127.238:5050` | **MLflow UI** — Xem model metrics | Không cần key |
| `http://140.245.127.238:9000` | **Kafdrop** — Xem Kafka topic browser | Không cần key |

---

## 🎤 Script Trình Bày Gợi Ý (5 phút)

1. **Mở Dashboard** (30s): "Đây là hệ thống phát hiện gian lận real-time, xử lý 6.3 triệu giao dịch PaySim"
2. **Chỉ Model Info** (30s): "Model Random Forest đạt F1 ~0.93, AUPRC ~0.94 trên dataset mất cân bằng cao (chỉ 0.13% fraud)"
3. **Demo SQL Injection** (1 phút): Nhập SQL vào search → không bị hack
4. **Demo PII Masking** (30s): Chỉ vào Account ID bị mask `C1234****`
5. **Demo API Key** (1 phút): Chạy curl có/không key → 401 vs 200
6. **Mở MLflow** (30s): Cho thầy thấy experiment tracking, metrics logged
7. **Tổng kết** (1 phút): "Hệ thống có 12 lớp bảo mật, 31 test cases passed"
