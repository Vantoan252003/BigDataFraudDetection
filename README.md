# Hệ Thống Phát Hiện Gian Lận Bằng Dữ Liệu Lớn (Big Data Fraud Detection)

## Tổng Quan
Dự án này là một đường ống (pipeline) phát hiện gian lận theo thời gian thực cho các giao dịch tài chính. Hệ thống sử dụng kiến trúc hướng sự kiện (event-driven) với Apache Kafka để truyền phát dữ liệu (streaming), PySpark (Structured Streaming) để xử lý dữ liệu và học máy (machine learning), PostgreSQL để lưu trữ dữ liệu an toàn, và Streamlit để cung cấp bảng điều khiển (dashboard) trực quan hóa dữ liệu theo thời gian thực.

## Các Tính Năng Chính
- **Real-Time Streaming**: Thu thập dữ liệu theo hướng sự kiện bằng Kafka và Zookeeper (đã được cấu hình tối ưu để chạy ở máy tính local).
- **Data Processing & ML**: Xử lý luồng dữ liệu đầu vào bằng các đoạn mã PySpark, đánh giá các giao dịch, và theo dõi các chỉ số của mô hình (ví dụ: AUC-ROC) thông qua **MLflow**.
- **Storage Sink**: Cơ sở dữ liệu PostgreSQL lưu trữ các giao dịch đã qua xử lý và các giao dịch bị đánh dấu gian lận (hỗ trợ tạo bảng phân biệt rõ chữ hoa/chữ thường tự động bởi Spark).
- **Interactive Dashboard (Streamlit)**: 
  - *Real-Time Dashboard*: Cập nhật thay đổi trên bảng điều khiển ngay khi có giao dịch gian lận.
  - *Transaction Explorer*: Bộ lọc dữ liệu, tìm kiếm, phân trang các lịch sử giao dịch trực tiếp từ Cơ sở dữ liệu.
  - *Analytics*: Các biểu đồ trực quan (Biểu đồ cột, Plotly histograms) để phân tích tần suất các loại giao dịch và gian lận.

## Yêu Cầu Hệ Thống
- **Docker** và **Docker Compose**
- **Git**

## Cài Đặt & Khởi Chạy

### 1. Tải Mã Nguồn Về Máy (Clone the repository)
```bash
git clone https://github.com/Vantoan252003/BigDataFraudDetection.git
cd BigDataFraudDetection
```

### 2. Thêm Dữ Liệu (🚨 BƯỚC BẮT BUỘC)
Do giới hạn lưu trữ của GitHub (chỉ cho phép tối đa 100MB mỗi file), các tệp dữ liệu nguyên gốc (`paysim.csv`, `creditcard.csv`) KHÔNG CÓ TRÊN GITHUB. **Hệ thống của bạn sẽ chạy lỗi nếu không làm bước này.**
1. Tạo một thư mục có tên `data/` trong thư mục gốc của project (ngang hàng với README.md).
2. Tải và thả file `paysim.csv` vô trong thư mục `data/` mà bạn vừa tạo để container `producer` có thể tìm thấy file.

### 3. Khởi chạy Containers
Thực thi dòng lệnh sau trên Terminal để build và khởi động tất cả Docker containers mà không cần treo màn hình (detached mode):
```bash
docker compose up -d --build
```
*Lệnh này sẽ đánh thức các services: Zookeeper, Kafka, Kafdrop, PostgreSQL, MLflow, Streamlit, và các consumer xử lý dữ liệu ở dưới nền.*

### 4. Khởi tạo Database và Huấn Luyện Mô Hình
Khi các containers đã trạng thái "Up" (đang chạy), thực thi các dòng lệnh PySpark dưới đây để khởi chạy cấu trúc Database và huấn luyện mô hình học máy của bạn:

**Bước A:** Nạp dữ liệu mô phỏng/blacklist vô PostgreSQL
```bash
docker compose run --rm trainer spark-submit jobs/blacklist_loader.py
```

**Bước B:** Huấn luyện mô hình (log điểm đánh giá AUC-ROC xuống MLflow)
```bash
docker compose run --rm trainer spark-submit scripts/train_paysim_model.py
```

*Lưu ý: Các containers thuộc nhóm consumer đã được setup để lo liệu các luồng giao dịch đẩy vào.*

### 5. Truy Cập Vào Giao Diện Máy Chủ
Truy cập thông qua các cổng cục bộ (localhost), click thẳng trực tiếp ở đây:

- 📊 **Streamlit Dashboard**: [http://localhost:8501](http://localhost:8501) (Nơi check giao dịch và phân tích số liệu)
- ⚙️ **Kafdrop (Kafka GUI)**: [http://localhost:9000](http://localhost:9000) (Kiểm tra Consumer lags, offset, và topics Kafka)
- 📈 **MLflow (Model UI)**: [http://localhost:5000](http://localhost:5000) (Theo dõi điểm số từ việc huấn luyện models)

## Tắt Hệ Thống
Để tắt tất cả project một cách mượt mà và trả lại RAM/CPU cho máy tính:
```bash
docker compose down
```
