"""
delta_writer.py — Delta Lake write utilities
Cung cấp helper functions để ghi DataFrame vào Delta Lake format trên MinIO (S3-compatible).

Tại sao Delta Lake?
- ACID transactions: đảm bảo không mất dữ liệu khi Spark crash giữa chừng
- Time travel: xem lại dữ liệu tại bất kỳ thời điểm nào (audit log, rollback)
- Schema enforcement: tự động reject row nếu schema không khớp
- Scalable: không bị giới hạn RAM/disk như PostgreSQL — ghi vào S3 object storage
- OPTIMIZE/VACUUM: compact small files tự động qua Airflow DAG
"""
import os
import logging

logger = logging.getLogger(__name__)

# ── MinIO / S3 config ─────────────────────────────────────────────────────────
MINIO_ENDPOINT  = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
AWS_ACCESS_KEY  = os.getenv("AWS_ACCESS_KEY_ID", "minioadmin")
AWS_SECRET_KEY  = os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin")
DELTA_BASE_PATH = os.getenv("DELTA_BASE_PATH", "s3a://fraud-lakehouse")


def configure_spark_for_delta(spark):
    """
    Cấu hình SparkSession để kết nối với MinIO (S3-compatible) và bật Delta Lake.
    Gọi hàm này sau khi tạo SparkSession.
    """
    hadoop_conf = spark.sparkContext._jsc.hadoopConfiguration()
    hadoop_conf.set("fs.s3a.endpoint",                    MINIO_ENDPOINT)
    hadoop_conf.set("fs.s3a.access.key",                  AWS_ACCESS_KEY)
    hadoop_conf.set("fs.s3a.secret.key",                  AWS_SECRET_KEY)
    hadoop_conf.set("fs.s3a.path.style.access",           "true")
    hadoop_conf.set("fs.s3a.impl",                        "org.apache.hadoop.fs.s3a.S3AFileSystem")
    hadoop_conf.set("fs.s3a.aws.credentials.provider",
                    "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider")
    hadoop_conf.set("fs.s3a.connection.ssl.enabled",      "false")
    logger.info("✅ Spark configured for Delta Lake on MinIO")


def write_delta_batch(batch_df, batch_id, table_name: str, partition_cols=None):
    """
    Ghi một micro-batch Spark DataFrame vào Delta Lake table trong MinIO.

    Args:
        batch_df:       DataFrame của micro-batch hiện tại
        batch_id:       ID của batch (từ foreachBatch)
        table_name:     Tên table (VD: "transactions", "fraud_transactions")
        partition_cols: Danh sách cột để partition (VD: ["type"]) — tối ưu query
    """
    if batch_df.isEmpty():
        logger.debug(f"Batch {batch_id}: empty, skipping Delta write for {table_name}")
        return

    path = f"{DELTA_BASE_PATH}/{table_name}"
    count = batch_df.count()

    writer = batch_df.write \
        .format("delta") \
        .mode("append") \
        .option("mergeSchema", "true")  # Tự động mở rộng schema nếu có cột mới

    if partition_cols:
        writer = writer.partitionBy(*partition_cols)

    writer.save(path)
    logger.info(f"📦 Delta write | batch={batch_id} | table={table_name} | rows={count:,} | path={path}")


def run_optimize(spark, table_name: str):
    """
    Chạy OPTIMIZE để compact small files thành file lớn hơn.
    Thường được gọi từ Airflow DAG, không phải từ streaming.
    Giảm số lượng files → tăng tốc đọc lên 10-100x.
    """
    path = f"{DELTA_BASE_PATH}/{table_name}"
    logger.info(f"🔧 Running OPTIMIZE on {path} ...")
    spark.sql(f"OPTIMIZE delta.`{path}`")
    logger.info(f"✅ OPTIMIZE done for {table_name}")


def run_vacuum(spark, table_name: str, retain_hours: int = 168):
    """
    Chạy VACUUM để xóa các files cũ không còn được reference bởi Delta log.
    Default retain 168h (7 ngày) để đảm bảo time-travel vẫn hoạt động trong 1 tuần.
    """
    path = f"{DELTA_BASE_PATH}/{table_name}"
    logger.info(f"🧹 Running VACUUM on {path} (retain={retain_hours}h) ...")
    spark.sql(f"SET spark.databricks.delta.retentionDurationCheck.enabled = false")
    spark.sql(f"VACUUM delta.`{path}` RETAIN {retain_hours} HOURS")
    logger.info(f"✅ VACUUM done for {table_name}")
