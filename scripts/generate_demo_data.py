"""
generate_demo_data.py — Tạo file CSV demo nhỏ (1000 rows) từ PaySim pattern
Dùng cho demo nhanh khi không có file paysim.csv lớn (~500MB)
"""
import csv
import random
import os

OUTPUT_PATH = os.getenv("DEMO_OUTPUT", "data/demo_paysim.csv")
NUM_ROWS = 1000
FRAUD_RATIO = 0.05  # 5% giao dịch sẽ là fraud

# PaySim column names
HEADERS = [
    "step", "type", "amount", "nameOrig", "oldbalanceOrg",
    "newbalanceOrig", "nameDest", "oldbalanceDest", "newbalanceDest",
    "isFraud", "isFlaggedFraud"
]

TRANSACTION_TYPES = ["TRANSFER", "CASH_OUT"]

# Danh sách account giả lập
FRAUD_ACCOUNTS = [f"C{random.randint(1000000, 9999999)}" for _ in range(20)]


def generate_normal_tx(step):
    """Tạo giao dịch bình thường"""
    amount = round(random.uniform(100, 50000), 2)
    old_balance = round(random.uniform(amount, amount * 5), 2)
    new_balance = round(old_balance - amount, 2)
    dest_old = round(random.uniform(0, 100000), 2)
    dest_new = round(dest_old + amount, 2)

    return {
        "step": step,
        "type": random.choice(TRANSACTION_TYPES),
        "amount": amount,
        "nameOrig": f"C{random.randint(1000000, 9999999)}",
        "oldbalanceOrg": old_balance,
        "newbalanceOrig": new_balance,
        "nameDest": f"C{random.randint(1000000, 9999999)}",
        "oldbalanceDest": dest_old,
        "newbalanceDest": dest_new,
        "isFraud": 0,
        "isFlaggedFraud": 0,
    }


def generate_fraud_tx(step):
    """Tạo giao dịch gian lận — rút toàn bộ tiền"""
    amount = round(random.uniform(100000, 9999999), 2)
    old_balance = amount  # rút chính xác toàn bộ
    dest_old = round(random.uniform(0, 50000), 2)

    return {
        "step": step,
        "type": "TRANSFER",
        "amount": amount,
        "nameOrig": random.choice(FRAUD_ACCOUNTS),
        "oldbalanceOrg": old_balance,
        "newbalanceOrig": 0.0,  # rút sạch
        "nameDest": f"C{random.randint(1000000, 9999999)}",
        "oldbalanceDest": dest_old,
        "newbalanceDest": round(dest_old + amount, 2),
        "isFraud": 1,
        "isFlaggedFraud": 0,
    }


def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    fraud_count = int(NUM_ROWS * FRAUD_RATIO)
    normal_count = NUM_ROWS - fraud_count

    rows = []
    for i in range(normal_count):
        step = (i % 24) + 1
        rows.append(generate_normal_tx(step))

    for i in range(fraud_count):
        step = random.randint(1, 24)
        rows.append(generate_fraud_tx(step))

    # Shuffle để trộn fraud với normal
    random.shuffle(rows)

    # Sort by step (giả lập thời gian)
    rows.sort(key=lambda x: x["step"])

    with open(OUTPUT_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"✅ Đã tạo {NUM_ROWS} giao dịch demo tại {OUTPUT_PATH}")
    print(f"   - Normal: {normal_count} | Fraud: {fraud_count}")
    print(f"   - Fraud accounts (blacklist): {', '.join(FRAUD_ACCOUNTS[:5])}...")


if __name__ == "__main__":
    main()
