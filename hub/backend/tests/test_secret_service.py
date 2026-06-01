"""Unit tests for secret service (Argon2id hash, Fernet encrypt, HMAC token)."""

import pytest

from app.services.secret_service import (
    encrypt_secret,
    generate_client_credentials,
    generate_retrieval_token,
    hash_retrieval_token,
    hash_secret,
    verify_secret,
)


@pytest.mark.smoke
def test_client_credentials_format():
    """generate_client_credentials() → ('cli_...', 'sec_...')"""
    client_id, client_secret = generate_client_credentials()
    assert client_id.startswith("cli_")
    assert client_secret.startswith("sec_")
    assert len(client_id) >= 12  # "cli_" + 8+ chars
    assert len(client_secret) >= 16


@pytest.mark.smoke
def test_argon2_hash_verify_round_trip():
    """hash_secret() → verify_secret(hashed, secret) ผ่าน + hash ไม่ leak plaintext."""
    _, plaintext = generate_client_credentials()
    h = hash_secret(plaintext)
    assert plaintext not in h  # ห้ามมี plaintext อยู่ใน hash
    assert h.startswith("$argon2id$"), "ต้องใช้ Argon2id (ไม่ใช่ bcrypt/sha)"
    # signature: verify_secret(hashed, secret) — args order ระวัง
    assert verify_secret(h, plaintext) is True


@pytest.mark.smoke
def test_argon2_rejects_wrong_secret():
    """verify_secret() กับ secret ที่ผิด → False"""
    h = hash_secret("correct-secret")
    assert verify_secret(h, "wrong-secret") is False


@pytest.mark.smoke
def test_retrieval_token_is_hmac_not_plaintext():
    """hash_retrieval_token() = HMAC-SHA256 hex (64 chars) ไม่ใช่ plaintext."""
    token = generate_retrieval_token()
    hashed = hash_retrieval_token(token)
    assert hashed != token  # ห้ามเก็บ plaintext
    assert len(hashed) == 64  # SHA256 hex
    # Deterministic — hash เดิมเสมอสำหรับ token เดิม
    assert hash_retrieval_token(token) == hashed


@pytest.mark.smoke
def test_fernet_encrypt_round_trip():
    """encrypt_secret() คืน ciphertext ที่ decrypt ได้กลับ (round-trip)."""
    from app.services.secret_service import decrypt_secret

    plain = "sec_test_value_12345"
    cipher = encrypt_secret(plain)
    assert cipher != plain
    assert plain not in cipher
    assert decrypt_secret(cipher) == plain
