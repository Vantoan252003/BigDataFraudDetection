# 🤖 Hệ Thống Phát Hiện Gian Lận Tài Chính (Big Data Fraud Detection)
**Tài liệu dành cho AI (Claude/ChatGPT) đọc để tạo Slide Thuyết Trình (PowerPoint/Canva)**

---

## 1. TỔNG QUAN DỰ ÁN (Executive Summary)
- Tên dự án: Xây dựng hệ thống phát hiện gian lận giao dịch tài chính thời gian thực (Real-time Fraud Detection) áp dụng kiến trúc Big Data (Lakehouse) và MLOps.
- Vấn đề giải quyết: Giao dịch tài chính diễn ra liên tục với khối lượng khủng (100 tx/giây). Hệ thống lưu trữ truyền thống (PostgreSQL) không chịu nổi tải lưu trữ lịch sử lớn để phân tích. Đồng thời, mô hình AI (phát hiện gian lận) theo thời gian sẽ bị "lỗi thời" do tội phạm thay đổi hành vi, cần phải tự động hóa quá trình học lại (retrain) mô hình thay vì làm thủ công.
- Giải pháp cốt lõi: Kết hợp Streaming Processing (PySpark, Kafka), Hồ dữ liệu hiện đại (Delta Lake, MinIO), và Điều phối tự động hóa (Apache Airflow) để tạo ra quy trình khép kín, bền vững với quy mô dữ liệu lớn.

---

## 2. SO SÁNH: KIẾN TRÚC CŨ vs KIẾN TRÚC MỚI (Lakehouse)
Đây là phần cực kỳ quan trọng để ăn điểm khi trình bày:

### Kiến Trúc Cũ (Ver 1.0)
- **Lưu trữ:** Mọi dữ liệu (hàng triệu dòng) đổ hết vào PostgreSQL.
- **Hạn chế:** 
  1. PostgreSQL là DB giao dịch (OLTP), khi data vọt lên hàng chục triệu dòng, việc query phân tích (GROUP BY, SUM) sẽ cực kỳ chậm và gây sập hệ thống (tràn RAM).
  2. Các công việc như Cập nhật sổ đen (Blacklist), Retrain Model AI phải chạy bằng tay.

### Kiến Trúc Mới - Lakehouse (Ver 2.0 - Hiện Tại)
- Áp dụng **Dual-Write (Ghi song song):**
  - **Dòng 1:** Ghi vào **PostgreSQL**. Chỉ để phục vụ giao diện Streamlit Dashboard hiển thị real-time (tốc độ cao trên số lượng data vừa đủ).
  - **Dòng 2 (MỚI):** Ghi toàn bộ dữ liệu vĩnh viễn vào **Delta Lake** (được lưu trữ trên MinIO - giống AWS S3).
- **Lợi ích của Delta Lake:**
  - ACID Transactions: Dữ liệu bị gián đoạn giữa chừng không bao giờ bị lỗi (corrupted).
  - Time Travel: Có thể truy vấn lại hình trạng dữ liệu vào 5 ngày trước.
  - Columnar Storage: Lưu bằng định dạng Parquet theo cột, giúp Spark đọc vào phân tích/retrain model cực kỳ nhanh (nhanh gấp 10-100 lần CSV/SQL).
  - Tách bạch giữa phần mềm lưu trữ (Storage) và tính toán (Compute), đây chính là đặc trưng của **Big Data Lakehouse**.

---

## 3. LUỒNG XỬ LÝ CHÍNH (Real-time Pipeline)
Khi một giao dịch mới gửi đến, nó đi qua 3 lớp phòng ngự (3 Layers of Defense) do `PySpark Structured Streaming` đảm nhiệm với độ trễ (latency) chỉ tính bằng mili-giây:

1. **Lớp 1: Redis Blacklist (Bắt nguội):** Truy vấn ngay vào Redis In-memory DB. Nếu tài khoản gửi hoặc nhận nằm trong sổ đen (Blacklist) -> Đánh dấu GIAN LẬN ngay lập tức (<1ms).
2. **Lớp 2: Rule-Based Engine (Máy học quy tắc):** Chỉ kiểm tra các giao dịch loại `TRANSFER` và `CASH_OUT` nếu rút sạch tiền (Drain Ratio = 1.0) -> Đánh dấu GIAN LẬN mức cao.
3. **Lớp 3: Machine Learning Model (AI):** Chạy Random Forest Classifier (nạp từ MLflow) phân tích dựa trên lịch sử giao dịch -> Dự đoán xác suất GIAN LẬN.

Sau khi qua 3 lớp, giao dịch được ghi xuống Hồ dữ liệu (Delta Lake) và CSDL Dashboard (Postgres). Nếu giao dịch bị phát hiện là GIAN LẬN, song song bắn một tín hiệu sang Kafka `fraud-alerts` để cảnh báo (có thể dùng gửi mail, tin nhắn sms, v.v).

---

## 4. QUY TRÌNH TỰ ĐỘNG HÓA MLOPS (Với Apache Airflow)
Đây là phần biểu diễn đỉnh cao "Tự động hóa" của dự án. Hệ thống cấu hình sẵn 3 DAGs (chu trình tự động) chạy định kỳ:

### DAG 1: `blacklist_daily_refresh` (Cập nhật Sổ Đen)
- **Chu kỳ:** Chạy lúc 00:00 hàng ngày.
- **Tác vụ:** Quét toàn bộ dữ liệu lịch sử trên hệ thống, phân tích các tài khoản vừa thực hiện hành vi gian lận trong 24h qua, sau đó tự động nạp thẳng (reload) vào siêu bộ nhớ Redis.
- **Giá trị:** Hệ thống tự động học thuộc mặt kẻ gian mới mỗi ngày.

### DAG 2: `model_weekly_retrain` (Huấn Luyện Lại Mô Hình AI)
- **Chu kỳ:** Chạy lúc 02:00 sáng Chủ Nhật hàng tuần.
- **Tác vụ:** Dùng Spark nạp toàn bộ dữ liệu khủng (hàng triệu dòng) từ hồ dữ liệu, Train lại mô hình Random Forest. Tự động ghi lại các hệ số (F1-Score, AUC-ROC, Precision) lên MLflow.
- **Giá trị:** Hành vi tội phạm công nghệ cao luôn thay đổi. Tính năng Retrain tự động đảm bảo AI của hệ thống trở nên thông minh hơn theo thời gian nhờ học từ dữ liệu mới, không bị Concept Drift (suy giảm độ chính xác). Đây là chuẩn **MLOps**.

### DAG 3: `delta_daily_compaction` (Dọn dẹp Hồ Dữ Liệu)
- **Chu kỳ:** Chạy lúc 03:00 hàng ngày.
- **Tác vụ:** Chạy 2 lệnh kinh điển của Delta Lake là `OPTIMIZE` (gom hàng vạn file rác 1MB thành vài chục file 128MB) và `VACUUM` (xóa các file lịch sử quá 7 ngày).
- **Giá trị:** File càng to, Spark đọc càng nhanh (ít I/O overhead). Compaction tự động tối ưu hóa tốc độ hệ thống Big Data và tiết kiệm ổ cứng.

---

## 5. KIẾN TRÚC HẠ TẦNG & CI/CD (DevOps)
*   **Docker Containerization:** Tách toàn bộ hệ thống thành 13 micro-containers (Zookeeper, Kafka, Spark Consumer, MLflow, MinIO, PostgreSQL, Airflow, FastAPI, Streamlit...).
*   **CI/CD Pipeline (GitHub Actions):** Tích hợp quy trình Continuous Deployment. Bất cứ khi code được push lên branch `main`:
    1. GitHub Actions sẽ tự động kiểm tra code.
    2. Tự động đóng gói Image mới và Push lên `ghcr.io` (GitHub Container Registry).
    3. Tự động SSH vào VPS Oracle Cloud để kéo code mới, cập nhật Docker container mà người dùng không cần can thiệp.
*   **Cloud Deployment:** Hệ thống đang chạy Live ổn định trên một con VM Oracle Cloud.

---

## TÓM TẮT ĐỂ CLAUDE TẠO SLIDE:
Bạn (Claude) hãy sử dụng toàn bộ thông tin trên để tạo ra **dàn ý cho 1 file thuyết trình dài 10 - 15 slides**. Slide phải có:
1. Tính chất vấn đề (Tại sao cần BigData/Airflow mà không phải chỉ dùng Python/Web bình thường).
2. Sơ đồ kiến trúc luồng dữ liệu.
3. 3 lớp bảo vệ (Rule, Redis, AI).
4. Hệ sinh thái tự động hóa với Airflow (3 DAGs).
5. Kết luận về tính mở rộng (Scalability) của hệ thống.
