"""
blacklist_loader.py — Load danh sách tài khoản đen từ PaySim vào Redis
Chạy 1 lần trước khi khởi động Kafka consumer
"""
import os
import redis
from pyspark.sql import SparkSession
from pyspark.sql.functions import col

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
PAYSIM_PATH = os.getenv("PAYSIM_PATH", "data/paysim.csv")
BLACKLIST_KEY = "fraud:blacklist"

def load_blacklist():
    spark = SparkSession.builder \
        .appName("BlacklistLoader") \
        .getOrCreate()

    # Lấy tất cả tài khoản đã từng thực hiện giao dịch gian lận
    df = spark.read.csv(PAYSIM_PATH, header=True, inferSchema=True)
    
    fraud_accounts = df.filter(col("isFraud") == 1) \
                       .select("nameOrig") \
                       .distinct() \
                       .rdd.flatMap(lambda x: x) \
                       .collect()

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
    
    # SADD batch — O(1) per member lookup
    pipe = r.pipeline()
    for account in fraud_accounts:
        pipe.sadd(BLACKLIST_KEY, account)
    pipe.execute()

    total = r.scard(BLACKLIST_KEY)
    print(f"Đã load {total:,} tài khoản đen vào Redis key '{BLACKLIST_KEY}'")
    spark.stop()

if __name__ == "__main__":
    load_blacklist()
