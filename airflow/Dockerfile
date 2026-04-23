FROM apache/airflow:2.9.2-python3.11

USER root
RUN apt-get update && apt-get install -y docker.io && rm -rf /var/lib/apt/lists/*
USER airflow

# Cài thêm provider để Airflow có thể gọi Docker commands
# (dùng cho các DAG chạy spark-submit bên trong containers)
RUN pip install --no-cache-dir \
    apache-airflow-providers-docker==3.10.0 \
    apache-airflow-providers-apache-spark==4.8.0
