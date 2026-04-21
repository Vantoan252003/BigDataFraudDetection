FROM apache/airflow:2.9.2-python3.11

# Cài thêm provider để Airflow có thể gọi Docker commands
# (dùng cho các DAG chạy spark-submit bên trong containers)
RUN pip install --no-cache-dir \
    apache-airflow-providers-docker==3.10.0 \
    apache-airflow-providers-apache-spark==4.8.0
