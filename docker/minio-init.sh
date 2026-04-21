#!/bin/sh
# minio-init.sh — Tạo các bucket cần thiết trong MinIO khi khởi động
# Được chạy bởi service minio-init (one-shot container)

set -e

echo "⏳ Waiting for MinIO to be ready..."
until mc alias set local http://minio:9000 "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}" 2>/dev/null; do
  sleep 2
done

echo "✅ MinIO is ready. Creating buckets..."

# Bucket chính cho Delta Lake (transactions + fraud)
mc mb --ignore-existing local/fraud-lakehouse

# Bucket riêng cho MLflow artifacts (thay thế local filesystem)
mc mb --ignore-existing local/mlflow-artifacts

# Bucket cho checkpoints Spark Streaming
mc mb --ignore-existing local/spark-checkpoints

# Thiết lập lifecycle: tự xóa file sau 90 ngày (tiết kiệm storage)
mc ilm add --expiry-days 90 local/spark-checkpoints

echo "✅ Buckets created successfully:"
mc ls local/
