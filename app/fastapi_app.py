"""
fastapi_app.py — Secured REST endpoint để inject giao dịch thủ công
Features: API Key Auth, Rate Limiting, CORS, Audit Logging, Input Validation
"""
import os
import json
import time
import logging
import hashlib
from datetime import datetime
from collections import defaultdict
from kafka import KafkaProducer
from fastapi import FastAPI, HTTPException, Request, Depends, Security
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from typing import Literal
import uvicorn

# ── Logging ───────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fraud_api")

# ── Config ────────────────────────────────────────────────────────
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "transactions-data")
FRAUD_API_KEY = os.getenv("FRAUD_API_KEY", "")
SECRET_KEY = os.getenv("SECRET_KEY", "default-secret")

# ── Rate Limiter ──────────────────────────────────────────────────
class RateLimiter:
    """In-memory sliding window rate limiter"""

    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = defaultdict(list)

    def is_allowed(self, client_ip: str) -> bool:
        now = time.time()
        # Cleanup old entries
        self.requests[client_ip] = [
            t for t in self.requests[client_ip]
            if now - t < self.window_seconds
        ]
        if len(self.requests[client_ip]) >= self.max_requests:
            return False
        self.requests[client_ip].append(now)
        return True

    def remaining(self, client_ip: str) -> int:
        now = time.time()
        recent = [t for t in self.requests.get(client_ip, []) if now - t < self.window_seconds]
        return max(0, self.max_requests - len(recent))


rate_limiter = RateLimiter(max_requests=100, window_seconds=60)

# ── FastAPI App ───────────────────────────────────────────────────
app = FastAPI(
    title="Fraud Detection API",
    version="2.0.0",
    description="Secured REST API for fraud detection system",
    docs_url="/docs" if os.getenv("ENV", "development") != "production" else None,
    redoc_url=None,
)

# ── CORS ──────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",     # Streamlit local
        "http://streamlit:8501",     # Streamlit in Docker
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── Security Headers Middleware ───────────────────────────────────
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response


# ── Rate Limiting Middleware ──────────────────────────────────────
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.is_allowed(client_ip):
        logger.warning(f"Rate limit exceeded for {client_ip}")
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please try again later."},
            headers={"Retry-After": "60"},
        )
    response = await call_next(request)
    response.headers["X-RateLimit-Remaining"] = str(rate_limiter.remaining(client_ip))
    return response


# ── Audit Logging Middleware ──────────────────────────────────────
@app.middleware("http")
async def audit_log_middleware(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    client_ip = request.client.host if request.client else "unknown"
    api_key = request.headers.get("X-API-Key", "")
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:8] if api_key else "none"

    logger.info(
        f"AUDIT | {client_ip} | {request.method} {request.url.path} | "
        f"status={response.status_code} | key={key_hash} | {duration:.3f}s"
    )
    return response


# ── API Key Authentication ────────────────────────────────────────
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(api_key_header)):
    """Xác thực API key cho các endpoint cần bảo vệ"""
    if not FRAUD_API_KEY:
        # Nếu chưa config API key → cho phép (dev mode)
        return "dev-mode"
    if not api_key or api_key != FRAUD_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized. Provide a valid API key via X-API-Key header.",
        )
    return api_key


# ── Global Exception Handler ─────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Không trả về stack trace cho client"""
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. Please contact the administrator."},
    )


# ── Kafka Producer ───────────────────────────────────────────────
producer = None
for i in range(15):
    try:
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8"),
        )
        logger.info("✅ Connected to Kafka successfully!")
        break
    except Exception as e:
        logger.warning(f"Waiting for Kafka to be ready... (attempt {i+1}/15)")
        time.sleep(3)

if producer is None:
    logger.error("❌ Could not connect to Kafka after 15 attempts")


# ── Models ────────────────────────────────────────────────────────
class Transaction(BaseModel):
    step: int = Field(default=1, ge=1, le=744, description="Simulation step (1-744)")
    type: Literal["TRANSFER", "CASH_OUT", "PAYMENT", "CASH_IN", "DEBIT"] = "TRANSFER"
    amount: float = Field(gt=0, lt=100_000_000, description="Transaction amount (> 0)")
    nameOrig: str = Field(
        default="C1234567890", min_length=2, max_length=50,
        description="Originator account ID",
    )
    oldbalanceOrg: float = Field(default=0.0, ge=0)
    newbalanceOrig: float = Field(default=0.0, ge=0)
    nameDest: str = Field(
        default="C9876543210", min_length=2, max_length=50,
        description="Destination account ID",
    )
    oldbalanceDest: float = Field(default=0.0, ge=0)
    newbalanceDest: float = Field(default=0.0, ge=0)
    isFraud: int = Field(default=0, ge=0, le=1)
    isFlaggedFraud: int = Field(default=0, ge=0, le=1)

    @field_validator("nameOrig", "nameDest")
    @classmethod
    def validate_account_id(cls, v):
        """Chỉ cho phép alphanumeric account IDs"""
        import re
        if not re.match(r"^[A-Za-z0-9_\-]+$", v):
            raise ValueError("Account ID must contain only alphanumeric characters, hyphens, or underscores")
        return v


# ── Endpoints ─────────────────────────────────────────────────────
@app.get("/health")
def health():
    """Public health check — không cần API key"""
    return {
        "status": "ok",
        "kafka": "connected" if producer else "disconnected",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "2.0.0",
    }


@app.post("/transaction")
def send_transaction(tx: Transaction, api_key: str = Depends(verify_api_key)):
    """Gửi 1 giao dịch vào Kafka — cần API key"""
    if producer is None:
        raise HTTPException(status_code=503, detail="Kafka producer is not available")

    try:
        future = producer.send(KAFKA_TOPIC, key=tx.nameOrig, value=tx.model_dump())
        producer.flush()
        record = future.get(timeout=10)
        return {
            "status": "sent",
            "topic": record.topic,
            "partition": record.partition,
            "offset": record.offset,
        }
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Failed to send transaction. Please try again later.",
        )


@app.post("/blacklist-transaction")
def send_blacklisted_transaction(api_key: str = Depends(verify_api_key)):
    """Gửi giao dịch từ tài khoản trong blacklist — cần API key"""
    if producer is None:
        raise HTTPException(status_code=503, detail="Kafka producer is not available")

    tx = {
        "step": 1,
        "type": "TRANSFER",
        "amount": 9999999.99,
        "nameOrig": "C1231006815",
        "oldbalanceOrg": 9999999.99,
        "newbalanceOrig": 0.0,
        "nameDest": "C553264065",
        "oldbalanceDest": 0.0,
        "newbalanceDest": 9999999.99,
        "isFraud": 1,
        "isFlaggedFraud": 0,
    }
    try:
        producer.send(KAFKA_TOPIC, key=tx["nameOrig"], value=tx)
        producer.flush()
        return {"status": "sent", "note": "Blacklisted account — should trigger alert"}
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Failed to send transaction. Please try again later.",
        )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
