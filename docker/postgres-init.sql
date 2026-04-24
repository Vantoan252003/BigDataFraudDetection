-- ══════════════════════════════════════════════════════════════════
-- PostgreSQL Initialization Script
-- Chạy tự động khi container postgres khởi tạo lần đầu
-- ══════════════════════════════════════════════════════════════════

-- Tạo schema chuyên dụng cho fraud detection
CREATE SCHEMA IF NOT EXISTS shop;

-- Bảng transactions: lưu tất cả giao dịch đã qua pipeline
CREATE TABLE IF NOT EXISTS shop.transactions (
    id              BIGSERIAL PRIMARY KEY,
    step            BIGINT,
    type            VARCHAR(20) NOT NULL,
    amount          DOUBLE PRECISION NOT NULL CHECK (amount >= 0),
    "nameOrig"      VARCHAR(50) NOT NULL,
    "oldbalanceOrg" DOUBLE PRECISION DEFAULT 0,
    "newbalanceOrig" DOUBLE PRECISION DEFAULT 0,
    "nameDest"      VARCHAR(50) NOT NULL,
    "oldbalanceDest" DOUBLE PRECISION DEFAULT 0,
    "newbalanceDest" DOUBLE PRECISION DEFAULT 0,
    "isFraud"       INTEGER DEFAULT 0,
    "isFlaggedFraud" INTEGER DEFAULT 0,
    balance_diff_orig      DOUBLE PRECISION,
    balance_diff_dest      DOUBLE PRECISION,
    is_transfer_or_cashout INTEGER DEFAULT 0,
    amount_to_balance_ratio DOUBLE PRECISION DEFAULT 0,
    blacklist_flag         INTEGER DEFAULT 0,
    rule_fraud_flag        INTEGER DEFAULT 0,
    is_fraud_detected      INTEGER DEFAULT 0,
    ingested_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bảng fraud_transactions: chỉ chứa giao dịch gian lận
CREATE TABLE IF NOT EXISTS shop.fraud_transactions (
    id              BIGSERIAL PRIMARY KEY,
    step            BIGINT,
    type            VARCHAR(20) NOT NULL,
    amount          DOUBLE PRECISION NOT NULL CHECK (amount >= 0),
    "nameOrig"      VARCHAR(50) NOT NULL,
    "oldbalanceOrg" DOUBLE PRECISION DEFAULT 0,
    "newbalanceOrig" DOUBLE PRECISION DEFAULT 0,
    "nameDest"      VARCHAR(50) NOT NULL,
    "oldbalanceDest" DOUBLE PRECISION DEFAULT 0,
    "newbalanceDest" DOUBLE PRECISION DEFAULT 0,
    "isFraud"       INTEGER DEFAULT 0,
    "isFlaggedFraud" INTEGER DEFAULT 0,
    balance_diff_orig      DOUBLE PRECISION,
    balance_diff_dest      DOUBLE PRECISION,
    is_transfer_or_cashout INTEGER DEFAULT 0,
    amount_to_balance_ratio DOUBLE PRECISION DEFAULT 0,
    blacklist_flag         INTEGER DEFAULT 0,
    rule_fraud_flag        INTEGER DEFAULT 0,
    is_fraud_detected      INTEGER DEFAULT 0,
    ingested_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bảng audit_log: ghi lại mọi hoạt động API
CREATE TABLE IF NOT EXISTS shop.audit_log (
    id          BIGSERIAL PRIMARY KEY,
    timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    client_ip   VARCHAR(45),
    method      VARCHAR(10),
    endpoint    VARCHAR(255),
    status_code INTEGER,
    user_agent  VARCHAR(500),
    api_key_hash VARCHAR(16)
);

-- Index cho performance
CREATE INDEX IF NOT EXISTS idx_transactions_ingested ON shop.transactions (ingested_at DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_type ON shop.transactions (type);
CREATE INDEX IF NOT EXISTS idx_transactions_fraud ON shop.transactions (is_fraud_detected);
CREATE INDEX IF NOT EXISTS idx_fraud_transactions_ingested ON shop.fraud_transactions (ingested_at DESC);
CREATE INDEX IF NOT EXISTS idx_fraud_transactions_name ON shop.fraud_transactions ("nameOrig");
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON shop.audit_log (timestamp DESC);

-- Restrict direct access — Spark writes via fraud_user, Streamlit reads only
GRANT USAGE ON SCHEMA shop TO fraud_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA shop TO fraud_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA shop TO fraud_user;

-- Log
DO $$ BEGIN RAISE NOTICE '✅ Database initialized with schema shop, tables, indexes, and permissions'; END $$;

-- Log
DO $$ BEGIN RAISE NOTICE '✅ Database schema shop initialized'; END $$;
