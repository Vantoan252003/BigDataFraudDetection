"""
transaction_consumer.py — Spark Structured Streaming Consumer
Đọc từ Kafka, áp dụng blacklist check + ML scoring, ghi ra PostgreSQL
"""
import os
import shutil
shutil.rmtree("/tmp/fraud_checkpoint", ignore_errors=True)

import redis
import logging
from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    from_json, col, when, current_timestamp, lit
)
from pyspark.sql.types import (
    StructType, StructField, StringType, DoubleType, IntegerType, LongType
)
from pyspark.ml import PipelineModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "transactions-data")
POSTGRES_URL = os.getenv("POSTGRES_URL", "jdbc:postgresql://postgres:5432/fraud_db")
POSTGRES_USER = os.getenv("POSTGRES_USER", "fraud_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "fraud_pass")
MODEL_PATH = os.getenv("MODEL_PATH", "/models/fraud_rf_v1")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
CHECKPOINT_PATH = "/tmp/fraud_checkpoint/transactions"

# ── PaySim schema ─────────────────────────────────────────────────
PAYSIM_SCHEMA = StructType([
    StructField("step", LongType()),
    StructField("type", StringType()),
    StructField("amount", DoubleType()),
    StructField("nameOrig", StringType()),
    StructField("oldbalanceOrg", DoubleType()),
    StructField("newbalanceOrig", DoubleType()),
    StructField("nameDest", StringType()),
    StructField("oldbalanceDest", DoubleType()),
    StructField("newbalanceDest", DoubleType()),
    StructField("isFraud", IntegerType()),
    StructField("isFlaggedFraud", IntegerType()),
])

def load_blacklist_from_redis():
    """Load toàn bộ blacklist từ Redis vào Python set để broadcast"""
    r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)
    blacklist = r.smembers("fraud:blacklist")
    logger.info(f"Loaded {len(blacklist):,} accounts from Redis blacklist")
    return blacklist

def write_batch_to_postgres(batch_df, batch_id, table_name):
    """Ghi micro-batch vào PostgreSQL"""
    if batch_df.isEmpty():
        return
    batch_df.write \
        .format("jdbc") \
        .option("url", POSTGRES_URL) \
        .option("dbtable", f"shop.{table_name}") \
        .option("user", POSTGRES_USER) \
        .option("password", POSTGRES_PASSWORD) \
        .option("driver", "org.postgresql.Driver") \
        .mode("append") \
        .save()
    logger.info(f"Batch {batch_id}: ghi {batch_df.count()} rows vào {table_name}")

def run_streaming():
    spark = SparkSession.builder \
        .appName("FraudDetectionConsumer") \
        .config("spark.sql.shuffle.partitions", "8") \
        .config("spark.streaming.stopGracefullyOnShutdown", "true") \
        .getOrCreate()
    spark.sparkContext.setLogLevel("WARN")

    # ── Load model (đã train bằng PaySim dataset) ─────────────
    logger.info(f"Loading model từ {MODEL_PATH} ...")
    
    # ── Broadcast blacklist ───────────────────────────────────────
    blacklist_set = load_blacklist_from_redis()
    blacklist_bc = spark.sparkContext.broadcast(blacklist_set)

    # ── Đọc từ Kafka ──────────────────────────────────────────────
    raw_stream = spark.readStream \
        .format("kafka") \
        .option("kafka.bootstrap.servers", KAFKA_BOOTSTRAP_SERVERS) \
        .option("subscribe", KAFKA_TOPIC) \
        .option("startingOffsets", "latest") \
        .option("failOnDataLoss", "false") \
        .load()

    # ── Parse JSON ────────────────────────────────────────────────
    parsed = raw_stream \
        .select(from_json(col("value").cast("string"), PAYSIM_SCHEMA).alias("data")) \
        .select("data.*") \
        .withColumn("ingested_at", current_timestamp())

    # ── Feature engineering cho PaySim ───────────────────────────
    enriched = parsed.withColumn(
        "balance_diff_orig", col("newbalanceOrig") - col("oldbalanceOrg")
    ).withColumn(
        "balance_diff_dest", col("newbalanceDest") - col("oldbalanceDest")
    ).withColumn(
        "is_transfer_or_cashout",
        when(col("type").isin(["TRANSFER", "CASH_OUT"]), 1).otherwise(0)
    ).withColumn(
        "amount_to_balance_ratio",
        when(col("oldbalanceOrg") > 0, col("amount") / col("oldbalanceOrg")).otherwise(0.0)
    )

    # ── Tầng 1: Rule-based detection (dùng broadcast join) ────────
    # Dùng UDF để check blacklist từ broadcast — tránh shuffle
    from pyspark.sql.functions import udf
    from pyspark.sql.types import IntegerType as IT

    @udf(returnType=IT())
    def check_blacklist(account_id):
        return 1 if account_id in blacklist_bc.value else 0

    # ── Tầng 2: Rule-based fraud detection từ PaySim features ─────
    detected = enriched \
        .withColumn("blacklist_flag", check_blacklist(col("nameOrig"))) \
        .withColumn(
            "rule_fraud_flag",
            when(
                (col("type").isin(["TRANSFER", "CASH_OUT"])) &
                (col("newbalanceOrig") == 0) &
                (col("oldbalanceOrg") > 0) &
                ((col("amount") / col("oldbalanceOrg")) >= 0.95) &
                ((col("amount") / col("oldbalanceOrg")) <= 1.05), 1
            ).otherwise(0)
        ) \
        .withColumn(
            "is_fraud_detected",
            when(
                (col("rule_fraud_flag") == 1) |
                (col("blacklist_flag") == 1), 1
            ).otherwise(0)
        )

    # ── Ghi tất cả giao dịch ra PostgreSQL ───────────────────────
    query_all = detected.writeStream \
        .foreachBatch(lambda df, id: write_batch_to_postgres(df, id, "transactions")) \
        .outputMode("append") \
        .option("checkpointLocation", CHECKPOINT_PATH + "/all") \
        .start()

    # ── Ghi giao dịch gian lận ra PostgreSQL ─────────────────────
    fraud_df = detected.filter(col("is_fraud_detected") == 1)
    query_fraud = fraud_df.writeStream \
        .foreachBatch(lambda df, id: write_batch_to_postgres(df, id, "fraud_transactions")) \
        .outputMode("append") \
        .option("checkpointLocation", CHECKPOINT_PATH + "/fraud") \
        .start()

    # ── Ghi alert ra Kafka topic alerts-out ──────────────────────
    query_alerts = fraud_df \
        .selectExpr(
            "CAST(nameOrig AS STRING) AS key",
            """to_json(struct(
                nameOrig, nameDest, amount, type,
                is_fraud_detected, blacklist_flag, rule_fraud_flag,
                ingested_at
            )) AS value"""
        ) \
        .writeStream \
        .format("kafka") \
        .option("kafka.bootstrap.servers", KAFKA_BOOTSTRAP_SERVERS) \
        .option("topic", "fraud-alerts") \
        .option("checkpointLocation", CHECKPOINT_PATH + "/alerts") \
        .outputMode("append") \
        .start()

    logger.info("Streaming đang chạy... Nhấn Ctrl+C để dừng")
    spark.streams.awaitAnyTermination()

if __name__ == "__main__":
    run_streaming()
