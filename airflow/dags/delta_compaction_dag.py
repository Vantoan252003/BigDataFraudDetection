"""
delta_compaction_dag.py — Airflow DAG tự động OPTIMIZE + VACUUM Delta tables hàng ngày

Tại sao cần DAG này?
- Spark Structured Streaming ghi dữ liệu theo micro-batch (mỗi batch nhỏ 1~2 MB).
- Sau 24h streaming với 100 tx/giây, Delta table sẽ có hàng ngàn files nhỏ.
- Các file nhỏ gây ra: query chậm (I/O overhead), metadata lớn, tốn chi phí lưu trữ.
- OPTIMIZE: gom nhiều file nhỏ → ít file lớn (~128MB/file) → query nhanh hơn 10-100x.
- VACUUM: xóa phiên bản cũ (>7 ngày) để giải phóng storage, giữ Delta log gọn.
"""
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator

default_args = {
    "owner": "fraud-detection",
    "depends_on_past": False,
    "start_date": datetime(2025, 1, 1),
    "email_on_failure": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

TABLES = ["transactions", "fraud_transactions"]

with DAG(
    dag_id="delta_daily_compaction",
    default_args=default_args,
    description="OPTIMIZE + VACUUM Delta tables để compact small files, dọn dẹp storage",
    schedule="0 3 * * *",   # Daily at 03:00 UTC (sau blacklist refresh 00:00)
    catchup=False,
    tags=["fraud-detection", "delta-lake", "maintenance"],
) as dag:

    # Task 1: Kiểm tra MinIO accessible
    check_minio = BashOperator(
        task_id="check_minio_health",
        bash_command=(
            "curl -sf http://minio:9000/minio/health/live > /dev/null "
            "&& echo 'MinIO OK' || (echo 'MinIO unreachable!' && exit 1)"
        ),
    )

    for table in TABLES:
        # Task 2a/2b: OPTIMIZE từng table — compact small files
        optimize = BashOperator(
            task_id=f"optimize_{table}",
            bash_command=(
                f"docker exec transaction_consumer "
                f"python3 -c \""
                f"from pyspark.sql import SparkSession; "
                f"from jobs.delta_writer import configure_spark_for_delta, run_optimize; "
                f"spark = SparkSession.builder"
                f"  .appName('DeltaOptimize')"
                f"  .config('spark.sql.extensions', 'io.delta.sql.DeltaSparkSessionExtension')"
                f"  .config('spark.sql.catalog.spark_catalog', 'org.apache.spark.sql.delta.catalog.DeltaCatalog')"
                f"  .getOrCreate(); "
                f"configure_spark_for_delta(spark); "
                f"run_optimize(spark, '{table}')\""
            ),
            execution_timeout=timedelta(minutes=20),
        )

        # Task 3a/3b: VACUUM — xóa files cũ (giữ lại 7 ngày = 168h để time-travel)
        vacuum = BashOperator(
            task_id=f"vacuum_{table}",
            bash_command=(
                f"docker exec transaction_consumer "
                f"python3 -c \""
                f"from pyspark.sql import SparkSession; "
                f"from jobs.delta_writer import configure_spark_for_delta, run_vacuum; "
                f"spark = SparkSession.builder"
                f"  .appName('DeltaVacuum')"
                f"  .config('spark.sql.extensions', 'io.delta.sql.DeltaSparkSessionExtension')"
                f"  .config('spark.sql.catalog.spark_catalog', 'org.apache.spark.sql.delta.catalog.DeltaCatalog')"
                f"  .getOrCreate(); "
                f"configure_spark_for_delta(spark); "
                f"run_vacuum(spark, '{table}', retain_hours=168)\""
            ),
            execution_timeout=timedelta(minutes=15),
        )

        check_minio >> optimize >> vacuum
