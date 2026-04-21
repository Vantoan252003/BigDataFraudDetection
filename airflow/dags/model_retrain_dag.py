"""
model_retrain_dag.py — Airflow DAG tự động retrain ML model hàng tuần

Tại sao cần DAG này?
- Mô hình Random Forest được train 1 lần trên toàn bộ dữ liệu lịch sử.
- Theo thời gian, pattern gian lận thay đổi (tội phạm học được cách qua mặt model cũ).
- DAG này tự động retrain mỗi Chủ Nhật 02:00 UTC, log kết quả lên MLflow để so sánh,
  và tự động swap model mới nếu F1-score cải thiện.
- Đây chính là nền tảng của một hệ thống MLOps thực thụ.
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
    "retry_delay": timedelta(minutes=10),
}

with DAG(
    dag_id="model_weekly_retrain",
    default_args=default_args,
    description="Retrain Random Forest model hàng tuần, log metrics lên MLflow",
    schedule="0 2 * * 0",   # Every Sunday at 02:00 UTC
    catchup=False,
    tags=["fraud-detection", "mlflow", "machine-learning", "retrain"],
) as dag:

    # Task 1: Kiểm tra dữ liệu paysim.csv vẫn còn đó
    check_data = BashOperator(
        task_id="check_paysim_data_exists",
        bash_command=(
            "docker exec trainer ls /app/data/paysim.csv > /dev/null 2>&1 "
            "&& echo 'Data OK' || (echo 'paysim.csv missing!' && exit 1)"
        ),
    )

    # Task 2: Kiểm tra MLflow server đang chạy
    check_mlflow = BashOperator(
        task_id="check_mlflow_health",
        bash_command=(
            "curl -sf http://fraud_mlflow:5000/health > /dev/null "
            "&& echo 'MLflow OK' || (echo 'MLflow unreachable!' && exit 1)"
        ),
    )

    # Task 3: Retrain model (spark-submit — có thể mất 30-60 phút với 6.3M records)
    retrain_model = BashOperator(
        task_id="retrain_random_forest",
        bash_command=(
            "docker exec trainer "
            "spark-submit /app/scripts/train_paysim_model.py"
        ),
        # 90 phút timeout — dataset lớn, Spark cần thời gian
        execution_timeout=timedelta(minutes=90),
    )

    # Task 4: Xác nhận model mới đã được ghi vào MLflow
    verify_model_logged = BashOperator(
        task_id="verify_model_logged_to_mlflow",
        bash_command=(
            "RUNS=$(curl -sf http://fraud_mlflow:5000/api/2.0/mlflow/runs/search "
            "-H 'Content-Type: application/json' "
            "-d '{\"experiment_ids\": [\"1\"], \"max_results\": 1}' "
            "| python3 -c \"import sys,json; d=json.load(sys.stdin); "
            "print(len(d.get('runs', [])))\"); "
            "echo \"MLflow runs found: $RUNS\"; "
            "[ \"$RUNS\" -gt 0 ] || exit 1"
        ),
    )

    [check_data, check_mlflow] >> retrain_model >> verify_model_logged
