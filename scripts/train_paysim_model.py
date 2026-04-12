"""
train_paysim_model.py — Train model trên PaySim dataset bằng PySpark MLlib
Features: amount, type (encoded), balance diffs, amount_ratio
Label: isFraud
"""
import os
import mlflow
import mlflow.spark
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, when
from pyspark.ml import Pipeline
from pyspark.ml.feature import VectorAssembler, StringIndexer, StandardScaler
from pyspark.ml.classification import RandomForestClassifier
from pyspark.ml.evaluation import BinaryClassificationEvaluator, MulticlassClassificationEvaluator

PAYSIM_PATH = os.getenv("PAYSIM_PATH", "data/paysim.csv")
MODEL_OUTPUT_PATH = os.getenv("MODEL_OUTPUT_PATH", "/models/fraud_paysim_v1")
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")

def train():
    spark = SparkSession.builder \
        .appName("PaySimModelTraining") \
        .config("spark.sql.shuffle.partitions", "8") \
        .getOrCreate()

    print("Đọc PaySim dataset ...")
    df = spark.read.csv(PAYSIM_PATH, header=True, inferSchema=True)
    
    # Chỉ dùng TRANSFER và CASH_OUT vì fraud chỉ xảy ra ở đây
    df = df.filter(col("type").isin(["TRANSFER", "CASH_OUT"]))
    
    # Feature engineering
    from pyspark.sql.functions import abs as spark_abs
    df = df.withColumn("balance_diff_orig", col("newbalanceOrig") - col("oldbalanceOrg")) \
           .withColumn("balance_diff_dest", col("newbalanceDest") - col("oldbalanceDest")) \
           .withColumn("amount_ratio_orig",
               when(col("oldbalanceOrg") > 0, col("amount") / col("oldbalanceOrg")).otherwise(0.0)) \
           .withColumn("zero_balance_after",
               when(col("newbalanceOrig") == 0, 1).otherwise(0)) \
           .withColumn(
               "drain_ratio",
               when(col("oldbalanceOrg") > 0, col("amount") / col("oldbalanceOrg")).otherwise(0.0)
           ) \
           .withColumn(
               "dest_balance_anomaly",
               when(
                   (col("amount") > 0) & 
                   (spark_abs(col("newbalanceDest") - col("oldbalanceDest") - col("amount")) > 1.0),
                   1
               ).otherwise(0)
           ) \
           .withColumn(
               "dest_is_merchant",
               when(col("nameDest").startswith("M"), 1).otherwise(0)
           ) \
           .withColumn(
               "is_large_transaction",
               when(col("amount") > 200000, 1).otherwise(0)
           )

    # Encode categorical 'type'
    type_indexer = StringIndexer(inputCol="type", outputCol="type_idx")

    feature_cols = [
        "amount", "type_idx",
        "oldbalanceOrg", "newbalanceOrig",
        "oldbalanceDest", "newbalanceDest",
        "balance_diff_orig", "balance_diff_dest",
        "amount_ratio_orig", "zero_balance_after",
        "drain_ratio", "dest_balance_anomaly", 
        "dest_is_merchant", "is_large_transaction"
    ]

    assembler = VectorAssembler(inputCols=feature_cols, outputCol="raw_features")
    scaler = StandardScaler(inputCol="raw_features", outputCol="features",
                            withMean=True, withStd=True)

    # Class weight
    fraud_count = df.filter(col("isFraud") == 1).count()
    normal_count = df.filter(col("isFraud") == 0).count()
    ratio = normal_count / fraud_count
    df = df.withColumn("classWeight",
                       (col("isFraud") * (ratio - 1) + 1).cast("double"))

    train_df, test_df = df.randomSplit([0.8, 0.2], seed=42)

    rf = RandomForestClassifier(
        labelCol="isFraud",
        featuresCol="features",
        weightCol="classWeight",
        numTrees=100,
        maxDepth=10,
        seed=42,
    )

    pipeline = Pipeline(stages=[type_indexer, assembler, scaler, rf])

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment("fraud-detection-paysim")

    with mlflow.start_run(run_name="RandomForest_PaySim_v1"):
        print("Đang train model trên PaySim ...")
        model = pipeline.fit(train_df)
        predictions = model.transform(test_df)

        auprc = BinaryClassificationEvaluator(
            labelCol="isFraud", rawPredictionCol="rawPrediction",
            metricName="areaUnderPR"
        ).evaluate(predictions)
        
        auc_roc = BinaryClassificationEvaluator(
            labelCol="isFraud", rawPredictionCol="rawPrediction",
            metricName="areaUnderROC"
        ).evaluate(predictions)
        
        f1 = MulticlassClassificationEvaluator(
            labelCol="isFraud", predictionCol="prediction", metricName="f1"
        ).evaluate(predictions)
        
        precision = MulticlassClassificationEvaluator(
            labelCol="isFraud", predictionCol="prediction", metricName="weightedPrecision"
        ).evaluate(predictions)
        
        recall = MulticlassClassificationEvaluator(
            labelCol="isFraud", predictionCol="prediction", metricName="weightedRecall"
        ).evaluate(predictions)

        print(f"AUPRC: {auprc:.4f} | AUC-ROC: {auc_roc:.4f} | F1: {f1:.4f} | Precision: {precision:.4f} | Recall: {recall:.4f}")
        mlflow.log_metric("auprc", auprc)
        mlflow.log_metric("auc_roc", auc_roc)
        mlflow.log_metric("f1_score", f1)
        mlflow.log_metric("precision", precision)
        mlflow.log_metric("recall", recall)
        
        mlflow.spark.log_model(model, "fraud_paysim_model")
        model.save(MODEL_OUTPUT_PATH)

        # Show execution plan
        predictions.explain(mode="formatted")

    spark.stop()
    print(f"Model lưu tại {MODEL_OUTPUT_PATH}")

if __name__ == "__main__":
    train()
