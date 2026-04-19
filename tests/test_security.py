"""
test_security.py — Security test suite
Tests: PII masking, input sanitization, amount validation, API auth logic
"""
import sys
import os
import re
import pytest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from security.encryption import mask_account_id, hash_account_id, sanitize_input, validate_amount


# ==================================================================
# TEST PII MASKING
# ==================================================================
class TestPIIMasking:
    def test_mask_normal_account(self):
        """C1234567890 → C1234******"""
        result = mask_account_id("C1234567890")
        assert result == "C1234******"
        assert "567890" not in result

    def test_mask_short_account(self):
        """Account ID ngắn hơn threshold → giữ nguyên"""
        result = mask_account_id("C123")
        assert result == "C123"

    def test_mask_empty(self):
        """Empty string → trả về chính nó"""
        result = mask_account_id("")
        assert result == ""

    def test_mask_none(self):
        """None → trả về None"""
        result = mask_account_id(None)
        assert result is None

    def test_mask_preserves_prefix(self):
        """Đảm bảo prefix letter + 4 digits được giữ"""
        result = mask_account_id("C9876543210")
        assert result.startswith("C9876")
        assert result.count("*") == 6

    def test_mask_different_lengths(self):
        """Test với các độ dài khác nhau"""
        assert mask_account_id("M12345") == "M1234*"
        assert mask_account_id("C1231006815") == "C1231******"


# ==================================================================
# TEST INPUT SANITIZATION
# ==================================================================
class TestInputSanitization:
    def test_sql_injection_blocked(self):
        """SQL injection phải bị loại bỏ ký tự đặc biệt"""
        malicious = "'; DROP TABLE shop.transactions; --"
        result = sanitize_input(malicious)
        assert "DROP" in result  # chữ vẫn giữ
        assert ";" not in result  # ký tự đặc biệt bị xóa
        assert "'" not in result
        assert "--" not in result

    def test_xss_blocked(self):
        """XSS script phải bị loại bỏ"""
        xss = "<script>alert('xss')</script>"
        result = sanitize_input(xss)
        assert "<" not in result
        assert ">" not in result

    def test_normal_input_preserved(self):
        """Input bình thường phải được giữ nguyên"""
        normal = "C1234567890"
        result = sanitize_input(normal)
        assert result == normal

    def test_max_length_enforced(self):
        """Input dài quá limit phải bị cắt"""
        long_input = "A" * 200
        result = sanitize_input(long_input, max_length=50)
        assert len(result) == 50

    def test_empty_input(self):
        result = sanitize_input("")
        assert result == ""

    def test_none_input(self):
        result = sanitize_input(None)
        assert result == ""

    def test_whitespace_trimmed(self):
        result = sanitize_input("  C123  ")
        assert result == "C123"

    def test_unicode_removed(self):
        """Ký tự unicode/emoji phải bị loại bỏ"""
        result = sanitize_input("C123🔥💀")
        assert result == "C123"


# ==================================================================
# TEST AMOUNT VALIDATION
# ==================================================================
class TestAmountValidation:
    def test_valid_amount(self):
        assert validate_amount(100.0) is True
        assert validate_amount(0.01) is True
        assert validate_amount(99_999_999.99) is True

    def test_zero_rejected(self):
        assert validate_amount(0) is False

    def test_negative_rejected(self):
        assert validate_amount(-100.0) is False

    def test_too_large_rejected(self):
        assert validate_amount(100_000_000) is False
        assert validate_amount(999_999_999.99) is False


# ==================================================================
# TEST HASHING (for audit)
# ==================================================================
class TestHashing:
    def test_hash_consistent(self):
        """Same input → same hash"""
        h1 = hash_account_id("C123")
        h2 = hash_account_id("C123")
        assert h1 == h2

    def test_hash_different_inputs(self):
        """Different inputs → different hashes"""
        h1 = hash_account_id("C123")
        h2 = hash_account_id("C456")
        assert h1 != h2

    def test_hash_length(self):
        """Hash phải có 16 ký tự"""
        result = hash_account_id("C123")
        assert len(result) == 16

    def test_hash_empty(self):
        result = hash_account_id("")
        assert result == ""

    def test_hash_irreversible(self):
        """Hash không chứa nguyên bản account ID"""
        result = hash_account_id("C1234567890")
        assert "C1234567890" not in result


# ==================================================================
# TEST SQL INJECTION PATTERNS
# ==================================================================
class TestSQLInjectionPatterns:
    """Test các pattern SQL injection phổ biến"""

    SQL_INJECTION_PATTERNS = [
        "' OR '1'='1",
        "'; DROP TABLE users; --",
        "' UNION SELECT * FROM information_schema.tables --",
        "1; UPDATE shop.transactions SET amount=0 --",
        "' OR 1=1 --",
        "admin'--",
        "1' ORDER BY 1--+",
        "' AND 1=(SELECT COUNT(*) FROM tabname); --",
    ]

    @pytest.mark.parametrize("payload", SQL_INJECTION_PATTERNS)
    def test_injection_sanitized(self, payload):
        """Tất cả SQL injection patterns phải bị sanitize"""
        result = sanitize_input(payload)
        # không chứa ký tự nguy hiểm
        assert "'" not in result
        assert ";" not in result
        assert "--" not in result
        assert "=" not in result
