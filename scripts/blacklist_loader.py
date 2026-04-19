# scripts/blacklist_loader.py
# Đọc toàn bộ tài khoản isFraud=1 từ paysim.csv → nạp vào Redis
# Chạy tự động trong docker-compose trước khi consumer khởi động

import os

import redis
from pyspark.sql import SparkSession
from pyspark.sql.functions import col

def load_blacklist():
    spark = SparkSession.builder.appName("BlacklistLoader").getOrCreate()
    df = spark.read.csv("data/paysim.csv", header=True, inferSchema=True)
    
    # Lấy tất cả tài khoản nguồn đã từng gian lận
    fraud_accounts = df.filter(col("isFraud") == 1) \
                       .select("nameOrig").distinct() \
                       .rdd.flatMap(lambda x: x).collect()

    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
    r = redis.Redis(host="fraud_redis", port=6379, password=REDIS_PASSWORD, decode_responses=True)
    r.delete("fraud:blacklist")  # xóa cũ trước khi nạp mới
    
    pipe = r.pipeline()
    for acc in fraud_accounts:
        pipe.sadd("fraud:blacklist", acc)
    pipe.execute()
    
    print(f"✅ Đã nạp {r.scard('fraud:blacklist'):,} tài khoản đen vào Redis")
    spark.stop()

if __name__ == "__main__":
    load_blacklist()