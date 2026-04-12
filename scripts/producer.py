"""
producer.py — Kafka Producer đọc từ PaySim dataset
Phát từng row theo thứ tự step để giả lập stream realtime
"""
import os
import json
import time
import logging
from kafka import KafkaProducer
from pyspark.sql import SparkSession

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "transactions-data")
PAYSIM_PATH = os.getenv("PAYSIM_PATH", "data/paysim.csv")
DELAY_SECONDS = float(os.getenv("PRODUCER_DELAY", "0.01"))  # 100 tx/giây

def create_producer():
    return KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8") if k else None,
        acks="all",
        retries=3,
        linger_ms=5,
        batch_size=16384,
    )

def stream_paysim():
    """
    Đọc PaySim CSV bằng Spark (không dùng Pandas cho file lớn),
    filter chỉ TRANSFER và CASH_OUT (fraud chỉ xảy ra ở 2 loại này),
    phát từng row vào Kafka theo thứ tự step.
    """
    spark = SparkSession.builder \
        .appName("PaySimProducer") \
        .config("spark.driver.memory", "2g") \
        .getOrCreate()
    spark.sparkContext.setLogLevel("WARN")

    logger.info(f"Đọc PaySim từ {PAYSIM_PATH} ...")
    df = spark.read.csv(PAYSIM_PATH, header=True, inferSchema=True)

    # Chỉ lấy TRANSFER và CASH_OUT — fraud chỉ xảy ra ở đây
    df_filtered = df.filter(df["type"].isin(["TRANSFER", "CASH_OUT"])) \
                    .orderBy("step")

    total = df_filtered.count()
    logger.info(f"Tổng số giao dịch cần stream: {total:,}")

    producer = create_producer()
    count = 0

    # Dùng toLocalIterator để không load hết vào memory
    for row in df_filtered.toLocalIterator():
        message = {
            "step": row["step"],
            "type": row["type"],
            "amount": float(row["amount"]),
            "nameOrig": row["nameOrig"],
            "oldbalanceOrg": float(row["oldbalanceOrg"]),
            "newbalanceOrig": float(row["newbalanceOrig"]),
            "nameDest": row["nameDest"],
            "oldbalanceDest": float(row["oldbalanceDest"]),
            "newbalanceDest": float(row["newbalanceDest"]),
            "isFraud": int(row["isFraud"]),
            "isFlaggedFraud": int(row["isFlaggedFraud"]),
        }
        producer.send(KAFKA_TOPIC, key=row["nameOrig"], value=message)
        count += 1

        if count % 1000 == 0:
            logger.info(f"Đã gửi {count:,}/{total:,} giao dịch")
            producer.flush()

        time.sleep(DELAY_SECONDS)

    producer.flush()
    producer.close()
    spark.stop()
    logger.info("Stream hoàn tất!")

if __name__ == "__main__":
    stream_paysim()
