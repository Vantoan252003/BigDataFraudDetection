#!/bin/bash
set -e

echo "Creating additional databases..."

# Tạo airflow_db nếu chưa tồn tại
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postgres" <<-EOSQL
    SELECT 'CREATE DATABASE airflow_db'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'airflow_db')\gexec
    GRANT ALL PRIVILEGES ON DATABASE airflow_db TO "$POSTGRES_USER";
EOSQL

echo "Running schema initialization for $POSTGRES_DB..."
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f /docker-entrypoint-initdb.d/02-schema.sql
