"""
blacklist_refresh_dag.py — Airflow DAG tự động reload Redis Blacklist hàng ngày

Tại sao cần DAG này?
- Danh sách tài khoản gian lận trong Redis chỉ được load 1 lần khi khởi động.
- Với 6.3M giao dịch sinh ra liên tục, mỗi ngày có thêm tài khoản mới bị phát hiện fraud.
- DAG này tự động chạy 00:00 UTC mỗi ngày, đảm bảo blacklist Redis luôn mới nhất,
  không cần dev phải SSH vào server chạy tay.
"""
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
import logging

logger = logging.getLogger(__name__)

default_args = {
    "owner": "fraud-detection",
    "depends_on_past": False,
    "start_date": datetime(2025, 1, 1),
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="blacklist_daily_refresh",
    default_args=default_args,
    description="Reload fraud blacklist vào Redis mỗi ngày 00:00 UTC",
    schedule="0 0 * * *",   # Daily at midnight UTC
    catchup=False,
    tags=["fraud-detection", "redis", "blacklist"],
) as dag:

    # Task 1: Kiểm tra Redis có sẵn sàng không
    check_redis = BashOperator(
        task_id="check_redis_health",
        bash_command=(
            "docker exec fraud_redis redis-cli "
            "-a $REDIS_PASSWORD ping | grep -q PONG && echo 'Redis OK'"
        ),
    )

    # Task 2: Reload blacklist bằng PySpark (đọc paysim.csv, push vào Redis)
    reload_blacklist = BashOperator(
        task_id="reload_blacklist_into_redis",
        bash_command=(
            "docker exec transaction_consumer "
            "spark-submit /app/jobs/blacklist_loader.py"
        ),
        # Đặt timeout 30 phút — file paysim.csv 500MB cần thời gian đọc
        execution_timeout=timedelta(minutes=30),
    )

    # Task 3: Kiểm tra kết quả
    verify_blacklist = BashOperator(
        task_id="verify_blacklist_count",
        bash_command=(
            "COUNT=$(docker exec fraud_redis redis-cli -a $REDIS_PASSWORD "
            "SCARD fraud:blacklist); "
            "echo \"Blacklist has $COUNT accounts\"; "
            "[ $COUNT -gt 0 ] || exit 1"
        ),
    )

    check_redis >> reload_blacklist >> verify_blacklist
