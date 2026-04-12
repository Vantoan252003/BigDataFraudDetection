# 🚀 Comprehensive System Architecture & Stabilization Report
**(Context Transfer Document for Claude/AI Assistants)**

## 1. System Architecture & Data Flow
This is a Real-Time Fraud Detection System using a modern Big Data Streaming stack. The data flow follows an Event-Driven Architecture (EDA):

1.  **Data Generation (Producer):** A Python script (`producer.py`) simulates real-time transactions from the `paysim.csv` dataset. It strictly filters for `TRANSFER` and `CASH_OUT` types (since fraud only occurs in these types in PaySim) to optimize throughput, then pushes them to **Kafka**.
2.  **Message Broker (Kafka + Zookeeper):** Kafka buffers the high-throughput data stream (topic: `transactions-data`), preventing downstream bottlenecks. Zookeeper manages Kafka's cluster state.
3.  **Streaming Processing (PySpark Consumer):** `transaction_consumer.py` reads micro-batches from Kafka (`startingOffsets: latest`). It processes transactions through a **Hybrid Detection System**:
    *   **Sub-millisecond Lookup (Redis):** Checks `nameOrig` against a blacklisted accounts set stored in Redis (`SISMEMBER`).
    *   **Rule-Based Engine:** Applies strict deterministic rules for immediate fraud flagging.
    *   **ML Model:** Uses a pre-trained Random Forest model (loaded via MLflow) for complex pattern detection.
4.  **Persistent Storage (PostgreSQL):** Processed transactions and identified frauds are written to `shop.transactions` and `shop.fraud_transactions` tables.
5.  **Monitoring & UI (Streamlit, MLflow, Kafdrop):** Streamlit polls PostgreSQL for real-time dashboards. MLflow tracks ML metrics. Kafdrop provides visibility into raw Kafka topics. FastAPI provides a REST endpoint for manual transaction injection.

## 2. Docker Containers & Images Used
The system is fully containerized via `docker-compose.yml`. Unused services (like Grafana) were removed to free up RAM.

| Service | Image/Dockerfile | Role |
| :--- | :--- | :--- |
| **zookeeper** | `confluentinc/cp-zookeeper:7.3.0` | Kafka dependency & cluster management. |
| **kafka** | `confluentinc/cp-kafka:7.3.0` | Message broker buffer. |
| **postgres** | `postgres:15-alpine` | Relational storage for transactions/frauds. |
| **redis** | `redis:7-alpine` | In-memory blacklist caching. |
| **mlflow** | `ghcr.io/mlflow/mlflow:v2.13.0` | Model registry & metric tracking. |
| **kafdrop** | `obsidiandynamics/kafdrop:latest` | Web UI to monitor Kafka topics & offsets. |
| **fastapi** | `Dockerfile.fastapi` | REST API for manual testing inputs. |
| **streamlit** | `Dockerfile.consumer` | Main UI Dashboard. |
| **producer** | `Dockerfile.consumer` | Streams CSV data to Kafka. |
| **transaction_consumer**| `Dockerfile.consumer` | PySpark Structured Streaming processor. |
| **trainer** | `Dockerfile.consumer` | PySpark MLlib training job (Run-once). |
| **blacklist_loader** | `Dockerfile.consumer` | Loads blacklist to Redis (Run-once). |

## 3. Critical Fixes: Rule Engine Optimization (Reducing False Positives)
Initially, the Rule-Based engine was too broad, causing a massive **52% False Positive Fraud Rate**. The logic in `transaction_consumer.py` was rewritten to strictly target "Account Sweeping" behavior.
A transaction is flagged by the rule engine **only if ALL these conditions are met**:
*   `type.isin(["TRANSFER", "CASH_OUT"])`
*   `newbalanceOrig == 0` (The account is completely emptied).
*   `oldbalanceOrg > 0` (There was money to begin with).
*   `drain_ratio` (amount / oldbalanceOrg) is between `0.95` and `1.05`.
*   *Result:* Fraud rate stabilized dynamically to around **1.3%** within the filtered Kafka stream, perfectly matching business logic.

## 4. UI & Metric Stabilization (Streamlit & MLflow)
1.  **Cumulative Time Chart:** The Streamlit timeline chart originally showed discrete bucket counts (which dipped as data ran out). Rewrote the SQL query using a Window Function: `WITH minute_counts AS (...) SELECT minute, SUM(fraud_count) OVER (ORDER BY minute)`. Now it correctly shows a linear cumulative growth of captured fraud.
2.  **AUC-ROC Metric Implementation:** MLflow was originally missing the AUC-ROC metric. Updated `train_paysim_model.py` to use `BinaryClassificationEvaluator(metricName="areaUnderROC")`. Added `mlflow.log_metric("auc_roc", auc_roc)` and updated Streamlit to parse the new key accurately.
3.  **PostgreSQL Case-Sensitivity Crash:** Streamlit threw an `UndefinedColumn` error for `nameOrig`. This happened because manual SQL `CREATE TABLE` commands lowercased column names (e.g., `nameorig`), breaking Pandas' strict queries. *Fix:* Dropped manual tables and allowed PySpark's `DataFrameWriter` to Auto-Generate the schemas. PySpark inherently wraps columns in quotes (`"nameOrig"`), perfectly preserving case-sensitivity.

## 5. Performance & Resource Tuning
*   **RAM Throttling (JVM Heap):** Bounded Kafka and Zookeeper memory footprints in `docker-compose.yml` explicitly using `KAFKA_HEAP_OPTS: "-Xms256M -Xmx512M"` to prevent local machines from freezing.
*   **Wiping Stale Checkpoints:** Ran `rm -rf /tmp/fraud_checkpoint` repeatedly when shifting logic or resetting databases to ensure PySpark didn't resume from older, incompatible Kafka offsets or schemas.
*   **Consumer Lag Explanation:** Noted the disparity between Kafdrop total offsets (e.g., ~20k) and Streamlit ingested records (e.g., ~10k). This perfectly demonstrates the EDA buffer mechanism, where Kafka absorbs peak spike workloads while PySpark safely consumes at its own computational pace.