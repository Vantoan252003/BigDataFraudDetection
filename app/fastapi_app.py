"""
fastapi_app.py — REST endpoint để inject giao dịch thủ công
Dùng khi demo trực tiếp trước giám khảo
"""
import os
import json
from kafka import KafkaProducer
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Literal
import uvicorn

app = FastAPI(title="Fraud Detection API", version="1.0.0")

import time

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "transactions-data")

producer = None
for i in range(15):
    try:
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8"),
        )
        print("Connected to Kafka successfully!")
        break
    except Exception as e:
        print(f"Waiting for Kafka to be ready... {e}")
        time.sleep(3)

class Transaction(BaseModel):
    step: int = 1
    type: Literal["TRANSFER", "CASH_OUT", "PAYMENT", "CASH_IN", "DEBIT"] = "TRANSFER"
    amount: float
    nameOrig: str = "C1234567890"
    oldbalanceOrg: float = 0.0
    newbalanceOrig: float = 0.0
    nameDest: str = "C9876543210"
    oldbalanceDest: float = 0.0
    newbalanceDest: float = 0.0
    isFraud: int = 0
    isFlaggedFraud: int = 0

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/transaction")
def send_transaction(tx: Transaction):
    """Gửi 1 giao dịch vào Kafka — dùng để demo thủ công"""
    try:
        future = producer.send(KAFKA_TOPIC, key=tx.nameOrig, value=tx.dict())
        producer.flush()
        record = future.get(timeout=10)
        return {
            "status": "sent",
            "topic": record.topic,
            "partition": record.partition,
            "offset": record.offset,
            "transaction": tx.dict(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/blacklist-transaction")
def send_blacklisted_transaction():
    """Gửi giao dịch từ tài khoản trong blacklist — demo fraud detection ngay lập tức"""
    tx = {
        "step": 1,
        "type": "TRANSFER",
        "amount": 9999999.99,
        "nameOrig": "C1231006815",  # account có trong PaySim fraud list
        "oldbalanceOrg": 9999999.99,
        "newbalanceOrig": 0.0,
        "nameDest": "C553264065",
        "oldbalanceDest": 0.0,
        "newbalanceDest": 9999999.99,
        "isFraud": 1,
        "isFlaggedFraud": 0,
    }
    producer.send(KAFKA_TOPIC, key=tx["nameOrig"], value=tx)
    producer.flush()
    return {"status": "sent", "note": "Blacklisted account — should trigger alert", "tx": tx}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
