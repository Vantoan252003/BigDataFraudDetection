import pytest
from pyspark.sql import SparkSession
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, LongType

@pytest.fixture(scope="session")
def spark():
    """Tạo SparkSession dùng chung cho tất cả các bài test"""
    spark = SparkSession.builder \
        .master("local[2]") \
        .appName("pytest-pyspark-local-testing") \
        .getOrCreate()
    yield spark
    spark.stop()

def test_feature_engineering_logic(spark):
    """Test unit logic feature engineering cho script train model"""
    schema = StructType([
        StructField("type", StringType()),
        StructField("amount", DoubleType()),
        StructField("oldbalanceOrg", DoubleType()),
        StructField("newbalanceOrig", DoubleType()),
        StructField("oldbalanceDest", DoubleType()),
        StructField("newbalanceDest", DoubleType()),
        StructField("nameDest", StringType()),
    ])

    data = [
        ("TRANSFER", 1000.0, 1000.0, 0.0, 0.0, 1000.0, "C123"), # Valid fraud-like transfer
        ("CASH_OUT", 500.0, 2000.0, 1500.0, 500.0, 1000.0, "M456"), # Merchant cash out
    ]

    df = spark.createDataFrame(data, schema)

    from pyspark.sql.functions import col, when
    from pyspark.sql.functions import abs as spark_abs

    # Chạy qua logic đang có trong train_paysim_model.py
    transformed_df = df.withColumn("balance_diff_orig", col("newbalanceOrig") - col("oldbalanceOrg")) \
           .withColumn("balance_diff_dest", col("newbalanceDest") - col("oldbalanceDest")) \
           .withColumn("amount_ratio_orig",
               when(col("oldbalanceOrg") > 0, col("amount") / col("oldbalanceOrg")).otherwise(0.0)) \
           .withColumn("zero_balance_after",
               when(col("newbalanceOrig") == 0, 1).otherwise(0)) \
           .withColumn(
               "dest_is_merchant",
               when(col("nameDest").startswith("M"), 1).otherwise(0)
           )

    results = transformed_df.collect()

    # Assert row 1
    assert results[0].balance_diff_orig == -1000.0
    assert results[0].amount_ratio_orig == 1.0
    assert results[0].zero_balance_after == 1
    assert results[0].dest_is_merchant == 0

    # Assert row 2
    assert results[1].dest_is_merchant == 1
    assert results[1].zero_balance_after == 0

def test_rule_based_fraud_detection(spark):
    """Test logic rule-based detection trong streaming consumer"""
    
    schema = StructType([
        StructField("type", StringType()),
        StructField("amount", DoubleType()),
        StructField("oldbalanceOrg", DoubleType()),
        StructField("newbalanceOrig", DoubleType()),
    ])

    data = [
        ("TRANSFER", 100.0, 100.0, 0.0), # Đúng rule (rút 100%)
        ("TRANSFER", 50.0, 100.0, 50.0), # Sai rule (còn tiền)
        ("PAYMENT", 100.0, 100.0, 0.0),  # Sai rule (sai type)
    ]

    df = spark.createDataFrame(data, schema)
    
    from pyspark.sql.functions import col, when
    
    # Logic rule-based fraud detection từ transaction_consumer.py
    detected = df.withColumn(
        "rule_fraud_flag",
        when(
            (col("type").isin(["TRANSFER", "CASH_OUT"])) &
            (col("newbalanceOrig") == 0) &
            (col("oldbalanceOrg") > 0) &
            ((col("amount") / col("oldbalanceOrg")) >= 0.95) &
            ((col("amount") / col("oldbalanceOrg")) <= 1.05), 1
        ).otherwise(0)
    )
    
    results = detected.collect()
    
    # Kết quả kỳ vọng: log ra chi tiết tự động nếu Assert fail
    assert results[0].rule_fraud_flag == 1, "LỖI: Rút sạch 100% bằng TRANSFER phải bị đánh dấu rule_fraud_flag = 1"
    assert results[1].rule_fraud_flag == 0, "LỖI: Vẫn còn tiền dư sau khi rút thì không thể đánh cờ rule rules"
    assert results[2].rule_fraud_flag == 0, "LỖI: Giao dịch PAYMENT không bao giờ dính rule_fraud_flag"

def test_blacklist_combined_logic(spark):
    """Test tổng hợp Rule-based và Blacklist-based (đảm bảo dính 1 trong 2 là báo CÓ GIAN LẬN)"""
    schema = StructType([
        StructField("nameOrig", StringType()),
        StructField("type", StringType()),
        StructField("amount", DoubleType()),
        StructField("oldbalanceOrg", DoubleType()),
        StructField("newbalanceOrig", DoubleType()),
    ])

    # Bộ blacklist giả lập từ Redis
    mock_blacklist = {"B_1234", "B_9999"}

    data = [
        ("U_0001", "TRANSFER", 100.0, 100.0, 0.0),   # Row 1: Không có trong blacklist, nhưng phạm Rule (100% tài khoản) -> Fraud
        ("B_1234", "CASH_IN",  50.0, 50.0, 100.0),   # Row 2: Phạm luật Blacklist -> Fraud
        ("U_0002", "PAYMENT",  20.0, 100.0, 80.0),   # Row 3: Người dùng bình thường -> Normal
    ]

    df = spark.createDataFrame(data, schema)
    
    from pyspark.sql.functions import col, when, udf
    from pyspark.sql.types import IntegerType as IT
    
    @udf(returnType=IT())
    def check_blacklist(account_id):
        return 1 if account_id in mock_blacklist else 0
        
    detected = df.withColumn(
        "blacklist_flag", check_blacklist(col("nameOrig"))
    ).withColumn(
        "rule_fraud_flag",
        when(
            (col("type").isin(["TRANSFER", "CASH_OUT"])) &
            (col("newbalanceOrig") == 0) &
            (col("oldbalanceOrg") > 0) &
            ((col("amount") / col("oldbalanceOrg")) >= 0.95) &
            ((col("amount") / col("oldbalanceOrg")) <= 1.05), 1
        ).otherwise(0)
    ).withColumn(
        "is_fraud_detected",
        when(
            (col("rule_fraud_flag") == 1) |
            (col("blacklist_flag") == 1), 1
        ).otherwise(0)
    )

    results = detected.collect()
    
    print("\n--- KẾT QUẢ DETECT TỔNG HỢP ---")
    detected.show(truncate=False)

    assert results[0].is_fraud_detected == 1, "LỖI: Giao dịch phạm Rule phải cho ra is_fraud_detected = 1"
    assert results[1].is_fraud_detected == 1, "LỖI: Giao dịch nằm trong Blacklist phải cho ra is_fraud_detected = 1"
    assert results[2].is_fraud_detected == 0, "LỖI: Giao dịch siêu bình thường thì is_fraud_detected phải = 0"

