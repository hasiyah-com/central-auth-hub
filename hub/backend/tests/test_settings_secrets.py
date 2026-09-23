"""secret ใน Settings ต้องไม่หลุดออกทาง repr/str/error — เขียนก่อน implementation (RED).

**ที่มา (B78):** ระหว่างรัน RED ของ B77 เทสตัวหนึ่งเรียก
`monkeypatch.setattr(settings, "jwt_clock_skew_seconds", 0)` ก่อนที่ฟิลด์จะมีอยู่
pytest จึงแสดง `AttributeError` ที่ข้อความมี `repr(settings)` ทั้งก้อน — Google client
secret, SMTP app password, LINE secret, webhook key และ Telegram bot token ออกมาใน
output ของเทสครบทุกตัว เพราะทุกฟิลด์เป็น `str` ธรรมดา

ข้อผิดพลาดใดๆ ที่พิมพ์ settings (traceback, log, error ของ pydantic) ให้ผลแบบเดียวกัน
ทางแก้: secret เป็น `SecretStr` (repr/str/dump แสดง `**********`) และ URL ที่อาจมี
รหัสผ่านหรือ token ถูกปิดใน repr · โค้ดที่ใช้ค่าจริงต้องเรียก `.get_secret_value()`
ตรงจุดที่ใช้เท่านั้น
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from app.config import Settings

SECRET_FIELDS = (
    "secret_key",
    "secret_encryption_key",
    "secret_encryption_keys_legacy",
    "google_client_secret",
    "line_client_secret",
    "smtp_password",
    "webhook_shared_key",
    "alert_telegram_bot_token",
)

# ฟิลด์ที่ชื่อคล้าย secret แต่ไม่ใช่ — ต้องระบุเหตุผลทุกตัว
NOT_SECRET = {
    "jwt_private_key_path": "path ไม่ใช่ตัว key",  # pragma: allowlist secret
    "jwt_public_key_path": "path ของ public key",
    "jwt_active_kid": "kid เป็นข้อมูลสาธารณะใน JWKS",
    "jwt_extra_public_keys": "path ของ public key",
    "jwt_access_token_expire_minutes": "อายุ token",
    "jwt_refresh_token_expire_days": "อายุ token",
    "jwt_clock_skew_seconds": "ความคลาดของนาฬิกา",
    "rate_limit_token": "อัตรา rate limit",
    "calibration_sha256": "hash ของไฟล์สาธารณะ",
    "google_client_id": "client id เป็นข้อมูลสาธารณะ",
    "line_client_id": "client id เป็นข้อมูลสาธารณะ",
    "passkey_required_after_days": "จำนวนวัน",
    "passkey_grace_period_days": "จำนวนวัน",
    "webauthn_max_passkeys_per_user": "จำนวน passkey",
}
_SECRETISH = ("secret", "password", "token", "key", "credential")

SENTINELS = {name: f"SENTINEL-{name}-9f3c" for name in SECRET_FIELDS}
DB_PW = "SENTINEL-dbpass-9f3c"
REDIS_PW = "SENTINEL-redispass-9f3c"
HOOK_TOKEN = "SENTINEL-hookpath-9f3c"


@pytest.fixture
def cfg() -> Settings:
    return Settings(
        **SENTINELS,
        database_url=f"postgresql+psycopg2://hub:{DB_PW}@postgres:5432/hub_test",
        redis_url=f"redis://:{REDIS_PW}@redis:6379/15",
        alert_webhook_url=f"https://hooks.example.com/services/{HOOK_TOKEN}",
    )


def _all_sentinels() -> list[str]:
    return [*SENTINELS.values(), DB_PW, REDIS_PW, HOOK_TOKEN]


def _assert_clean(text: str) -> None:
    leaked = [s for s in _all_sentinels() if s in text]
    assert not leaked, f"secret หลุด: {leaked}"


# ── ชนิดของฟิลด์ ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", SECRET_FIELDS)
def test_secret_fields_are_secretstr(cfg, name):
    assert isinstance(getattr(cfg, name), SecretStr)


@pytest.mark.parametrize("name", SECRET_FIELDS)
def test_secret_value_is_still_available_explicitly(cfg, name):
    assert getattr(cfg, name).get_secret_value() == SENTINELS[name]


def test_every_secret_looking_field_is_classified():
    """ฟิลด์ใหม่ที่ชื่อคล้าย secret ต้องเป็น SecretStr หรือมีเหตุผลใน NOT_SECRET."""
    unclassified = [
        name
        for name, field in Settings.model_fields.items()
        if any(w in name for w in _SECRETISH)
        and name not in NOT_SECRET
        and field.annotation is not SecretStr
    ]
    assert not unclassified, f"ต้องจัดประเภท: {unclassified}"


# ── ช่องทางที่ค่าเคยหลุด ─────────────────────────────────────────────────


def test_repr_and_str_do_not_reveal_secrets(cfg):
    _assert_clean(repr(cfg))
    _assert_clean(str(cfg))


def test_json_dump_does_not_reveal_secrets(cfg):
    _assert_clean(cfg.model_dump_json())


def test_the_original_incident_attribute_error_is_clean(cfg, monkeypatch):
    """เหตุการณ์จริงของ B78 — setattr ฟิลด์ที่ไม่มี แล้ว error พา repr ออกมา."""
    with pytest.raises(AttributeError) as e:
        monkeypatch.setattr(cfg, "no_such_field_b78", 0)
    _assert_clean(str(e.value))


def test_validation_error_does_not_echo_other_secrets():
    with pytest.raises(Exception) as e:
        Settings(**SENTINELS, jwt_clock_skew_seconds=999)
    _assert_clean(str(e.value))


def test_url_hosts_stay_visible_for_diagnosis(cfg):
    """ปิดแค่ส่วนลับ — host/db ยังต้องเห็นเพื่อวินิจฉัยว่าชี้ถูกฐานข้อมูลไหม."""
    text = repr(cfg)
    assert "postgres:5432/hub_test" in text
    assert "redis:6379/15" in text
    assert "hooks.example.com" in text


def test_url_values_themselves_are_unchanged(cfg):
    """การปิดทำเฉพาะตอนแสดงผล ค่าที่ใช้เชื่อมต่อจริงต้องครบ."""
    assert DB_PW in cfg.database_url
    assert REDIS_PW in cfg.redis_url
    assert HOOK_TOKEN in cfg.alert_webhook_url


# ── พฤติกรรมเดิมต้องไม่เปลี่ยน ──────────────────────────────────────────


def test_production_fail_fast_still_detects_default_secret_key():
    s = Settings(app_env="production", secret_key="dev-secret-change-me")
    with pytest.raises(RuntimeError) as e:
        s.validate_production()
    assert "secret_key" in str(e.value)
    assert "dev-secret-change-me" not in str(e.value)


def test_production_fail_fast_still_detects_empty_encryption_key():
    s = Settings(app_env="production", secret_key="x" * 64, secret_encryption_key="")
    with pytest.raises(RuntimeError) as e:
        s.validate_production()
    assert "secret_encryption_key" in str(e.value)


def test_production_accepts_real_values():
    Settings(
        app_env="production", secret_key="x" * 64, secret_encryption_key="y" * 44
    ).validate_production()


def test_empty_secret_reads_as_empty():
    """โค้ดที่เช็ค 'ตั้งค่าหรือยัง' ต้องอ่านค่าจริง ไม่ใช่ความจริงของ object."""
    s = Settings(webhook_shared_key="")
    assert s.webhook_shared_key.get_secret_value() == ""
