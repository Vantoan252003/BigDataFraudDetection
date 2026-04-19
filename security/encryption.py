"""
encryption.py — PII Protection & Data Masking Utilities
Cung cấp các hàm mã hóa, giải mã, và masking cho dữ liệu nhạy cảm
"""
import hashlib
import os
import re


def mask_account_id(account_id: str, visible_chars: int = 4) -> str:
    """
    Mask account ID để hiển thị trên dashboard.
    Input:  C1234567890
    Output: C1234******
    """
    if not account_id or len(account_id) <= visible_chars + 1:
        return account_id
    prefix = account_id[:visible_chars + 1]  # giữ prefix letter + 4 digits
    masked = prefix + "*" * (len(account_id) - visible_chars - 1)
    return masked


def hash_account_id(account_id: str) -> str:
    """
    SHA-256 hash cho audit logging — không thể reverse.
    Dùng khi cần log account nhưng không muốn lộ PII.
    """
    if not account_id:
        return ""
    salt = os.getenv("SECRET_KEY", "default-salt")
    return hashlib.sha256(f"{salt}:{account_id}".encode()).hexdigest()[:16]


def sanitize_input(user_input: str, max_length: int = 100) -> str:
    """
    Sanitize user input — loại bỏ ký tự nguy hiểm.
    Dùng cho search fields trên Streamlit.
    """
    if not user_input:
        return ""
    # Truncate
    sanitized = user_input[:max_length]
    # Chỉ giữ alphanumeric, space, dash, underscore
    sanitized = re.sub(r"[^a-zA-Z0-9\s\-_]", "", sanitized)
    # Remove SQL comment sequences
    sanitized = sanitized.replace("--", "")
    return sanitized.strip()


def validate_amount(amount: float) -> bool:
    """Validate transaction amount trong phạm vi hợp lý"""
    return 0 < amount < 100_000_000
