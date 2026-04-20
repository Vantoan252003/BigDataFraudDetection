import csv
import random
import os
import sys

# Chấp nhận tham số dòng từ command line, mặc định 3 triệu
try:
    NUM_ROWS = int(sys.argv[1]) if len(sys.argv) > 1 else 3_000_000
except ValueError:
    NUM_ROWS = 3_000_000

OUTPUT_PATH = os.getenv("DEMO_OUTPUT", "data/paysim.csv")
FRAUD_RATIO = 0.0004  # 0.04% giao dịch sẽ là fraud

# PaySim column names
HEADERS = [
    "step", "type", "amount", "nameOrig", "oldbalanceOrg",
    "newbalanceOrig", "nameDest", "oldbalanceDest", "newbalanceDest",
    "isFraud", "isFlaggedFraud"
]

TRANSACTION_TYPES = ["TRANSFER", "CASH_OUT", "PAYMENT", "CASH_IN", "DEBIT"]

# Danh sách account giả lập
FRAUD_ACCOUNTS = [f"C{random.randint(1000000, 9999999)}" for _ in range(20)]


def generate_normal_tx(step):
    """Tạo giao dịch bình thường"""
    # Lượng tiền normal giờ có thể lên lới 500k để trùng lặp với fraud
    amount = round(random.uniform(10, 500000) if random.random() > 0.1 else random.uniform(500000, 2000000), 2)
    old_balance = round(random.uniform(0, amount * 10), 2)
    new_balance = round(max(0, old_balance - amount) if random.random() > 0.4 else old_balance + amount, 2)
    dest_old = round(random.uniform(0, 1000000), 2)
    dest_new = round(dest_old + amount, 2)

    tx_type = random.choices(TRANSACTION_TYPES, weights=[20, 20, 30, 20, 10])[0]

    return {
        "step": step,
        "type": tx_type,
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
    """Tạo giao dịch gian lận — rút tiền có noise để model không đạt 1.00"""
    # Lượng tiền có thể nhỏ từ 10k đến lới 2M
    amount = round(random.uniform(10000, 2000000), 2)
    
    # 70% rút sạch, 30% chừa lại chút đỉnh
    if random.random() > 0.3:
        old_balance = amount
        new_balance = 0.0
    else:
        old_balance = amount + round(random.uniform(10, 5000), 2)
        new_balance = round(old_balance - amount, 2)
        
    dest_old = round(random.uniform(0, 50000), 2)
    
    tx_type = random.choices(["TRANSFER", "CASH_OUT", "PAYMENT"], weights=[45, 45, 10])[0]

    return {
        "step": step,
        "type": tx_type,
        "amount": amount,
        "nameOrig": random.choice(FRAUD_ACCOUNTS),
        "oldbalanceOrg": old_balance,
        "newbalanceOrig": new_balance,
        "nameDest": f"C{random.randint(1000000, 9999999)}",
        "oldbalanceDest": dest_old,
        "newbalanceDest": round(dest_old + amount, 2) if tx_type != "PAYMENT" else dest_old,
        "isFraud": 1,
        "isFlaggedFraud": 1 if amount > 200000 else 0,
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

    # Thêm nhiễu nhãn (Label Noise) để mô hình không bao giờ đạt 1.00
    # Đảm bảo Precision và Recall rơi vào khoảng 0.85 - 0.95 (giống thực tế)
    for row in rows:
        if row["isFraud"] == 1:
            if random.random() < 0.15: # 15% fraud bị gán nhãn sai thành normal -> giảm Recall
                row["isFraud"] = 0
                row["isFlaggedFraud"] = 0
        else:
            if random.random() < 0.0002: # 0.02% normal bị gán nhãn sai thành fraud -> giảm Precision
                row["isFraud"] = 1

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
