"""ตาราง calibration v1 ที่เก็บเข้า repo — ตรวจว่าไฟล์กับ metadata เป็นชุดเดียวกัน.

เขียนก่อนวางไฟล์ (RED) · ตารางนี้สร้างจากประชากรจำลอง P48-T2 (validation 32 โปรไฟล์)
ใช้ให้คะแนนสามชั้นเทียบกันได้ระหว่างเก็บข้อมูล shadow เท่านั้น — **ห้ามอ้างเป็น FPR จริง**

ระบบยังไม่โหลดไฟล์นี้เอง ต้องตั้ง `CALIBRATION_PATH` + `CALIBRATION_SHA256` และให้
เกณฑ์/gamma ใน env ตรงกับ metadata (`validate_startup`)

**ปลายบรรทัด:** repo ตั้ง `core.autocrlf=true` ถ้าไฟล์ถูกแปลงเป็น CRLF ตอน checkout
sha256 จะไม่ตรงและระบบไม่ยอม start · `.gitattributes` ต้องกันไว้
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND = Path(__file__).resolve().parents[1]
ARTIFACTS = BACKEND / "app" / "security" / "artifacts"
ARTIFACT = ARTIFACTS / "calibration_v1.json"
META = ARTIFACTS / "calibration_v1.meta.json"

REQUIRED_META = {
    "version",
    "sha256",
    "gamma",
    "thresholds",
    "population",
    "fit_seeds",
    "check_seeds",
    "created_at",
    "generator_commit",
    "synthetic_only",
    "activation",
}


@pytest.fixture(scope="module")
def meta() -> dict:
    assert META.exists(), f"ไม่พบ {META}"
    return json.loads(META.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def artifact() -> dict:
    assert ARTIFACT.exists(), f"ไม่พบ {ARTIFACT}"
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_meta_has_every_required_field(meta):
    assert REQUIRED_META <= set(meta), f"ขาด {sorted(REQUIRED_META - set(meta))}"


def test_file_hash_matches_meta(meta):
    assert hashlib.sha256(ARTIFACT.read_bytes()).hexdigest() == meta["sha256"]


def test_file_has_no_carriage_returns():
    """CRLF เข้ามาเมื่อไร hash เปลี่ยนและ validate_startup จะไม่ยอม start."""
    assert b"\r" not in ARTIFACT.read_bytes()


def test_meta_matches_artifact_contents(meta, artifact):
    assert meta["version"] == artifact["version"]
    assert meta["gamma"] == artifact["fusion"]["gamma"]
    for level in ("warn", "challenge", "block"):
        assert meta["thresholds"][level] == artifact["derived_thresholds"][level], level
    assert meta["fit_seeds"] == artifact["source"]["fit_seeds"]
    assert meta["check_seeds"] == artifact["source"]["check_seeds"]
    assert meta["population"] == artifact["source"]["population"]


def test_artifact_is_marked_synthetic(meta, artifact):
    assert meta["synthetic_only"] is True
    assert "synthetic" in artifact["version"]


def test_startup_accepts_the_artifact_with_meta_values(meta):
    from app.security import calibration

    cfg = SimpleNamespace(
        l3_mode="shadow_hybrid",
        calibration_path=str(ARTIFACT),
        calibration_sha256=meta["sha256"],
        calibration_version=meta["version"],
        l4_gamma=meta["gamma"],
        l4_threshold_warn=meta["thresholds"]["warn"],
        l4_threshold_challenge=meta["thresholds"]["challenge"],
        l4_threshold_block=meta["thresholds"]["block"],
    )
    calibration.validate_startup(cfg)


def test_artifact_passes_builder_validation(artifact):
    core = pytest.importorskip("scripts.calibration_core")
    assert core.validate_artifact(artifact, min_samples=1000) == []


def test_artifact_carries_no_identifiers():
    blob = ARTIFACT.read_text(encoding="utf-8")
    for word in ("@", "email", "user_id", "alias", "google_sub", "ip_address"):
        assert word not in blob, f"พบ {word!r} ในตาราง calibration"


def test_artifact_is_not_loaded_without_configuration():
    from app.config import settings
    from app.security import calibration

    if settings.calibration_path is None:
        assert calibration.CALIBRATION_FILE is None


def test_gitattributes_protects_artifact_bytes():
    parents = BACKEND.parents
    repo = parents[1] if len(parents) > 1 else BACKEND
    attrs = repo / ".gitattributes"
    if not attrs.exists() and not (repo / ".git").exists():
        pytest.skip(".gitattributes ไม่ได้ mount ในคอนเทนเนอร์ — ตรวจบน host")
    text = attrs.read_text(encoding="utf-8")
    assert "hub/backend/app/security/artifacts/** -text" in text
