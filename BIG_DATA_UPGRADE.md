# 🏗️ Big Data Upgrade v2.0 — Airflow + Delta Lake + CI/CD

> **Phiên bản:** v2.0 | **Ngày:** 2026-04-21 | **Tác giả:** AI Upgrade

---

## 📋 Mục Lục
1. [Tổng quan kiến trúc mới](#1-tổng-quan-kiến-trúc-mới)
2. [Delta Lake + MinIO — Tại sao?](#2-delta-lake--minio--tại-sao)
3. [Apache Airflow — Tại sao?](#3-apache-airflow--tại-sao)
4. [CI/CD GitHub Actions — Tại sao?](#4-cicd-github-actions--tại-sao)
5. [So sánh Trước/Sau](#5-so-sánh-trướcsau)
6. [Hướng dẫn khởi chạy](#6-hướng-dẫn-khởi-chạy)
7. [Luồng hoạt động sau nâng cấp](#7-luồng-hoạt-động-sau-nâng-cấp)
8. [Cloud Deployment](#8-cloud-deployment)

---

## 1. Tổng Quan Kiến Trúc Mới

```
                     paysim.csv (6.3M tx)
                           │
                    ┌──────▼──────┐
                    │  Producer   │  100 tx/giây
                    └──────┬──────┘
                           │
                    ┌──────▼──────────────┐
                    │  Kafka: transactions│  Buffer trung gian
                    └──────┬──────────────┘
                           │
         ┌─────────────────▼──────────────────────┐
         │        PySpark Structured Streaming     │
         │  Lớp 1: Redis Blacklist (<1ms)          │
         │  Lớp 2: Rule Engine                     │
         │  Lớp 3: ML Model (Random Forest)        │
         └──────┬──────────────┬───────────────────┘
                │              │
                │    ┌─────────▼────────┐
                │    │  Kafka           │
                │    │  fraud-alerts    │  Chỉ gian lận
                │    └──────────────────┘
                │
        ┌───────▼─────────────────────────────────────┐
        │           Dual-Write Output (MỚI)            │
        │                                              │
        │  ┌──────────────┐   ┌────────────────────┐  │
        │  │  PostgreSQL  │   │ Delta Lake (MinIO)  │  │
        │  │  (real-time) │   │ (analytical store)  │  │
        │  │  → Streamlit │   │ ACID + Time Travel  │  │
        │  └──────────────┘   └────────────────────┘  │
        └─────────────────────────────────────────────┘
                │
        ┌───────▼────────────────────────────────────┐
        │      Apache Airflow (MỚI)                  │
        │  DAG 1: Blacklist Refresh (daily 00:00)    │
        │  DAG 2: Model Retrain    (weekly Sun 02:00)│
        │  DAG 3: Delta Compaction (daily 03:00)     │
        └────────────────────────────────────────────┘
```

---

## 2. Delta Lake + MinIO — Tại sao?

### 🔴 Vấn Đề Với PostgreSQL Thuần Túy

| Giới hạn | Chi tiết |
|---|---|
| **RAM/Disk bị giới hạn** | PostgreSQL load data vào buffer pool trong RAM. Với 100 tx/giây × 24h = 8.6M rows/ngày, server 4GB RAM sẽ kẹt trong vài ngày |
| **OLTP ≠ OLAP** | PostgreSQL được thiết kế cho OLTP (giao dịch nhanh). Câu query phân tích như `GROUP BY type, SUM(amount)` trên 10M rows sẽ rất chậm |
| **Không có time-travel** | Không thể xem lại dữ liệu ở thời điểm T trong quá khứ — cần cho audit |
| **Single point of failure** | Nếu PostgreSQL container chết, mất toàn bộ dữ liệu đang streaming |

### ✅ Giải Pháp: Delta Lake trên MinIO

**Delta Lake** là open-source storage format (do Databricks phát triển) mang lại:

```
Delta Lake = Parquet Files + Transaction Log (_delta_log/)
```

| Tính năng | Lợi ích thực tế |
|---|---|
| **ACID Transactions** | Spark crash giữa chừng → không mất dữ liệu, tự rollback |
| **Time Travel** | `spark.read.format("delta").option("versionAsOf", 5).load(path)` — xem dữ liệu 5 phiên bản trước |
| **Schema Evolution** | Thêm cột mới vào PySpark → Delta tự mở rộng schema, không cần `ALTER TABLE` |
| **Scalable** | Lưu trên MinIO (S3-compatible) → lý thuyết vô giới hạn |
| **OPTIMIZE/VACUUM** | Compact small files → query nhanh hơn 10-100x |

**MinIO** là open-source S3-compatible object storage chạy hoàn toàn local (trong Docker). Không cần AWS.

### 🔄 Dual-Write Pattern

Hệ thống hiện tại **không xóa bỏ PostgreSQL** — thay vào đó ghi song song 2 nơi:

```python
def write_all_transactions(df, batch_id):
    write_batch_to_postgres(df, batch_id, "transactions")   # Real-time → Streamlit
    write_delta_batch(df, batch_id, "transactions")          # Analytics → MinIO
```

- **PostgreSQL**: Giữ nguyên cho `Streamlit Dashboard` — real-time, query nhanh trên ~10k rows gần nhất
- **Delta Lake**: Lưu toàn bộ lịch sử vĩnh viễn — cho phân tích batch, ML retrain, audit

---

## 3. Apache Airflow — Tại sao?

### 🔴 Vấn Đề Với Jobs Thủ Công

Trước đây, developer **phải SSH vào server và chạy tay**:
```bash
docker compose run --rm trainer spark-submit jobs/blacklist_loader.py  # Load blacklist
docker compose run --rm trainer spark-submit scripts/train_paysim_model.py  # Retrain
```

Điều này dẫn đến:
- ❌ Quên chạy → model cũ không bắt kịp pattern mới của tội phạm
- ❌ Không có lịch sử jobs thành công/thất bại
- ❌ Không có retry tự động khi job fail
- ❌ Không có alerting

### ✅ Giải Pháp: Apache Airflow với 3 DAGs

**DAG (Directed Acyclic Graph)** là định nghĩa workflow trong Airflow — gồm các tasks và thứ tự phụ thuộc giữa chúng.

#### DAG 1: `blacklist_daily_refresh` ⏰ 00:00 UTC hàng ngày
```
check_redis_health → reload_blacklist_into_redis → verify_blacklist_count
```
Đảm bảo Redis luôn có danh sách tài khoản gian lận mới nhất. Nếu có account gian lận mới được phát hiện hôm nay, sáng mai nó đã có trong blacklist.

#### DAG 2: `model_weekly_retrain` ⏰ 02:00 UTC Chủ Nhật
```
check_paysim_data ─┐
                   ├→ retrain_random_forest → verify_model_logged
check_mlflow    ───┘
```
Random Forest tự động học lại trên toàn bộ dataset. MLflow tự động log F1-score, AUC-ROC, Precision, Recall. Bạn có thể so sánh model tuần này vs tuần trước ngay trên MLflow UI.

#### DAG 3: `delta_daily_compaction` ⏰ 03:00 UTC hàng ngày
```
check_minio_health → optimize_transactions → vacuum_transactions
                   → optimize_fraud_transactions → vacuum_fraud_transactions
```
OPTIMIZE gom hàng nghìn file nhỏ (từ streaming micro-batches) thành vài chục file lớn. VACUUM xóa file cũ > 7 ngày.

### 🎯 Giá Trị Khi Báo Cáo

> *"Hệ thống của em có MLOps pipeline tự động: model tự động retrain hàng tuần, blacklist tự động cập nhật hàng ngày, và Delta Lake được tự động compact để đảm bảo hiệu năng. Tất cả được quản lý bởi Apache Airflow."*

Đây là đặc điểm của một **production-grade Data Platform**, không phải chỉ là đồ án sinh viên.

---

## 4. CI/CD GitHub Actions — Tại sao?

### 🔴 Vấn Đề Với Deploy Thủ Công
```bash
# Trước: Mỗi lần push code phải SSH + chạy tay
ssh user@server "cd project && git pull && docker compose up -d --build"
```
- ❌ Build có thể thành công local nhưng fail trên server (environment khác nhau)
- ❌ Nếu có bug, không ai biết build nào bị lỗi
- ❌ Deploy có thể xảy ra lúc nửa đêm khi không ai để ý

### ✅ Giải Pháp: GitHub Actions - 2 Workflows

**CI (`.github/workflows/ci.yml`)** — chạy khi push hoặc PR:
1. Chạy 31 security tests tự động
2. Build Docker images để verify không bị lỗi syntax

**CD (`.github/workflows/cd.yml`)** — chạy khi push lên `main`:
1. Login vào `ghcr.io` (GitHub Container Registry — **miễn phí**)
2. Build và push 3 images: `fraud-consumer`, `fraud-fastapi`, `fraud-airflow`
3. (Tùy chọn) SSH vào VPS và tự động restart services với image mới

```
git push origin main
      ↓
GitHub Actions kích hoạt tự động
      ↓
Build + Test (~5 phút)
      ↓
Push images lên ghcr.io
      ↓
ghcr.io/your-username/fraud-detection-consumer:latest  ✅
ghcr.io/your-username/fraud-detection-fastapi:latest   ✅
ghcr.io/your-username/fraud-detection-airflow:latest   ✅
      ↓
(Nếu cấu hình SSH_HOST secret) → Auto-deploy lên VPS
```

### Layer Caching
CD workflow dùng `cache-from: type=gha` — GitHub Actions cache layers giữa các lần build. Lần đầu build 15 phút, các lần sau chỉ 2-3 phút.

---

## 5. So Sánh Trước/Sau

| Tính năng | v1.0 (Trước) | v2.0 (Sau) |
|---|---|---|
| **Storage** | PostgreSQL (OLTP only) | PostgreSQL + Delta Lake trên MinIO |
| **Analytics** | Query PostgreSQL (chậm với data lớn) | Query Delta Lake (columnar, fast scan) |
| **Time Travel** | ❌ | ✅ 7 ngày |
| **Blacklist refresh** | Thủ công (chạy terminal) | Tự động hàng ngày 00:00 |
| **Model retrain** | Thủ công (chạy terminal) | Tự động hàng tuần Chủ Nhật |
| **File compaction** | ❌ | Tự động hàng ngày 03:00 |
| **Deploy** | Thủ công SSH | Auto-deploy khi push lên main |
| **Image registry** | Docker local only | ghcr.io (public cloud) |
| **Services** | 8 containers | 13 containers |
| **New ports** | — | 8080 (Airflow), 9001 (MinIO UI), 9002 (MinIO S3) |

---

## 6. Hướng Dẫn Khởi Chạy

### Bước 1: Thêm biến môi trường mới

```bash
# Mở file .env và thêm các biến sau (xem .env.example để tham khảo)
echo "MINIO_ROOT_USER=minioadmin" >> .env
echo "MINIO_ROOT_PASSWORD=minioadmin123" >> .env
echo "AWS_ACCESS_KEY_ID=minioadmin" >> .env
echo "AWS_SECRET_ACCESS_KEY=minioadmin123" >> .env
echo "MINIO_ENDPOINT=http://minio:9000" >> .env
echo "DELTA_BASE_PATH=s3a://fraud-lakehouse" >> .env

# Sinh Airflow Fernet key
python3 -c "from cryptography.fernet import Fernet; print('AIRFLOW_FERNET_KEY=' + Fernet.generate_key().decode())" >> .env
echo "AIRFLOW_UID=50000" >> .env
```

### Bước 2: Khởi chạy toàn bộ hệ thống

```bash
docker compose up -d --build
```

> ⚠️ **Lưu ý:** Lần đầu build sẽ lâu hơn (~10-15 phút) vì cần download Delta Lake JARs và build Airflow image.

### Bước 3: Kiểm tra các services mới

```bash
# Xem trạng thái tất cả containers
docker compose ps

# Chờ airflow-init hoàn tất (status: Exited (0))
docker compose logs airflow-init --tail=20

# Kiểm tra MinIO buckets đã tạo
docker compose logs minio-init
```

### Bước 4: Truy cập giao diện

| Service | URL | Tài khoản |
|---|---|---|
| 📊 Streamlit Dashboard | http://localhost:8501 | — |
| ✈️ Airflow UI | http://localhost:8080 | admin / admin |
| 🗄️ MinIO Console | http://localhost:9001 | minioadmin / minioadmin123 |
| 📈 MLflow | http://localhost:5050 | — |
| ⚙️ Kafdrop | http://localhost:9000 | — |

### Bước 5: Kích hoạt DAGs trong Airflow

1. Vào http://localhost:8080, đăng nhập `admin / admin`
2. Tìm 3 DAGs: `blacklist_daily_refresh`, `model_weekly_retrain`, `delta_daily_compaction`
3. Bật toggle ▶️ để kích hoạt
4. Click **"Trigger DAG"** để chạy thử thủ công

---

## 7. Luồng Hoạt Động Sau Nâng Cấp

Luồng real-time (streaming path) **không thay đổi** so với v1.0:

```
paysim.csv → Producer (100 tx/s) → Kafka (transactions-data)
           → PySpark:
               Lớp 1: Redis Blacklist check
               Lớp 2: Rule Engine (TRANSFER/CASH_OUT + drain_ratio)
               Lớp 3: ML Model (Random Forest)
           → Dual-Write:
               PostgreSQL → Streamlit Dashboard
               Delta Lake → MinIO (s3a://fraud-lakehouse/)
           → Kafka (fraud-alerts) → Consumer khác
```

Luồng batch (automation path) là **hoàn toàn mới**:

```
Airflow Scheduler (cron)
  00:00 → blacklist_daily_refresh DAG
            Redis ← paysim.csv (tài khoản gian lận mới nhất)
  02:00 Sun → model_weekly_retrain DAG
              PySpark train → MLflow log → /models/ save
  03:00 → delta_daily_compaction DAG
            OPTIMIZE (compact files) + VACUUM (dọn cũ)
```

---

## 8. Cloud Deployment

### Cách Đơn Giản Nhất: Dùng ghcr.io Images (Sau khi push lên main)

```yaml
# Trên VPS của bạn, sửa docker-compose.yml để dùng pre-built images
services:
  transaction_consumer:
    image: ghcr.io/YOUR_USERNAME/fraud-detection-consumer:latest
    # Xóa build: block
```

### Cấu Hình Auto-Deploy

Thêm các secrets sau vào GitHub repository (`Settings → Secrets → Actions`):

| Secret | Giá trị |
|---|---|
| `SSH_HOST` | IP của VPS (VD: `123.456.789.0`) |
| `SSH_USER` | Username SSH (VD: `ubuntu`) |
| `SSH_PRIVATE_KEY` | Nội dung private key (từ file `.pem`) |
| `PROJECT_PATH` | Đường dẫn project trên VPS (VD: `/home/ubuntu/FraudDetectionSystem`) |

Sau khi cấu hình, **mỗi lần `git push origin main` → GitHub Actions tự động deploy lên server**.

### Providers Miễn Phí Gợi Ý

| Provider | Free Tier | Phù Hợp Cho |
|---|---|---|
| **Oracle Cloud** | VM 4 vCPU + 24GB RAM (**vĩnh viễn miễn phí**) | Chạy full stack |
| **fly.io** | 3 shared VMs miễn phí | FastAPI + Streamlit |
| **Railway** | $5 credit/tháng | Demo nhanh |
| **Render** | Free web service | FastAPI only |

> 💡 **Gợi ý cho sinh viên:** Oracle Cloud Free Tier (Always Free) đủ mạnh để chạy toàn bộ stack gồm Kafka, Spark, PostgreSQL, MinIO, và Airflow. Đây là lựa chọn tốt nhất cho demo đồ án.

---

## 📁 Files Được Thêm/Sửa Trong Nâng Cấp Này

| File | Thay đổi | Mục đích |
|---|---|---|
| `jobs/delta_writer.py` | **[MỚI]** | Helper functions ghi Delta Lake |
| `jobs/transaction_consumer.py` | **[SỬA]** | Thêm dual-write Delta Lake |
| `Dockerfile.consumer` | **[SỬA]** | Thêm Delta Lake + S3A JARs |
| `docker/minio-init.sh` | **[MỚI]** | Tạo MinIO buckets tự động |
| `docker/postgres-init.sql` | **[SỬA]** | Thêm `airflow_db` database |
| `airflow/Dockerfile` | **[MỚI]** | Airflow image với Spark provider |
| `airflow/dags/blacklist_refresh_dag.py` | **[MỚI]** | DAG reload Redis blacklist |
| `airflow/dags/model_retrain_dag.py` | **[MỚI]** | DAG retrain ML model |
| `airflow/dags/delta_compaction_dag.py` | **[MỚI]** | DAG OPTIMIZE + VACUUM |
| `docker-compose.yml` | **[SỬA]** | Thêm MinIO, minio-init, Airflow |
| `.env.example` | **[SỬA]** | Thêm biến MinIO + Airflow |
| `.github/workflows/cd.yml` | **[MỚI]** | CI/CD push images lên ghcr.io |
