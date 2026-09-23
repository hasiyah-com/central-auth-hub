"""ความสมบูรณ์ของตาราง calibration ตอน start — เขียนก่อน implementation (RED).

ขั้นที่ 7 ของแผน Hybrid Shadow: "หาก calibration หายหรือ hash ไม่ตรง ระบบต้องปิด
shadow_hybrid และบันทึกสาเหตุ ไม่ควรใช้ raw score แทนเงียบ ๆ"

**อันตรายที่เทสนี้กัน — ตารางถูกเปิดใช้โดยไม่ตั้งใจ**
เดิม `calibration.py` โหลด `calibration_v1.json` อัตโนมัติถ้ามีไฟล์วางอยู่ข้าง ๆ
หลักฐานทุกชั้นจะกลายเป็นเปอร์เซ็นไทล์ทันที (กฎเดียวที่ยิงได้ราว 0.99) ขณะที่
เกณฑ์ยังเป็นชุดเก่า 0.50/0.70/0.85 -> การตัดสินจริงเกือบทุกครั้งกลายเป็น block
โดยไม่มีอะไรฟ้อง · การเปิดใช้ตารางจึงต้อง **ประกาศชัด** และเกณฑ์ต้องมาจากตารางเดียวกัน
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from app.security import calibration as C


def _artifact(**over) -> dict:
    art = {
        "version": "cal-test-v1",
        "quantiles": {
            "rule": [0.0] * 90 + [0.5] * 10,
            "behavior": [0.0] * 50 + [0.3] * 50,
            "anomaly_point": [i / 100 for i in range(100)],
            "anomaly_sequence": [i / 100 for i in range(100)],
        },
        "derived_thresholds": {
            "warn": 0.9,
            "challenge": 0.95,
            "block": 0.99,
            "from_percentile": {"warn": 0.9, "challenge": 0.95, "block": 0.99},
        },
        "fusion": {"gamma": 1.0, "config": "B"},
    }
    art.update(over)
    return art


def _write(tmp_path, art) -> tuple:
    path = tmp_path / "calibration_v1.json"
    path.write_text(json.dumps(art), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _settings(path, sha, **over):
    base = dict(
        l3_mode="shadow_hybrid",
        calibration_path=str(path) if path else None,
        calibration_sha256=sha,
        calibration_version="cal-test-v1",
        l4_gamma=1.0,
        l4_threshold_warn=0.9,
        l4_threshold_challenge=0.95,
        l4_threshold_block=0.99,
    )
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _fresh_table():
    C.reload_for_tests()
    yield
    C.reload_for_tests()


# ══════════════════════════════════════════════════════════════════════════════
# 1. การเปิดใช้ตารางต้องประกาศชัด
# ══════════════════════════════════════════════════════════════════════════════


def test_default_path_is_not_the_neighbour_file():
    """ไม่ตั้ง CALIBRATION_PATH = ไม่มีตาราง แม้จะมีไฟล์วางอยู่ข้าง calibration.py."""
    from app.config import settings

    if settings.calibration_path is None:
        assert C.CALIBRATION_FILE is None


def test_expected_hash_mismatch_means_no_table(tmp_path, monkeypatch):
    path, _ = _write(tmp_path, _artifact())
    monkeypatch.setattr(C, "CALIBRATION_FILE", path)
    monkeypatch.setattr(C.settings, "calibration_sha256", "0" * 64, raising=False)
    C.reload_for_tests()
    out = C.calibrate("rule", 0.5)
    assert out.calibrated is False, "hash ไม่ตรงต้องไม่ใช้ตาราง"
    assert C.status()["state"] == "sha_mismatch"


def test_expected_hash_match_loads_table(tmp_path, monkeypatch):
    path, sha = _write(tmp_path, _artifact())
    monkeypatch.setattr(C, "CALIBRATION_FILE", path)
    monkeypatch.setattr(C.settings, "calibration_sha256", sha, raising=False)
    C.reload_for_tests()
    assert C.calibrate("rule", 0.5).calibrated is True
    st = C.status()
    assert st["state"] == "ok"
    assert st["sha256"] == sha
    assert st["version"] == "cal-test-v1"


def test_explicit_file_without_expected_hash_still_loads_for_experiments(
    tmp_path, monkeypatch
):
    """การทดลองและเทสชี้ไฟล์เองโดยตรง — ยังใช้ได้ แต่สถานะต้องบอกว่าไม่ได้ตรวจ."""
    path, _ = _write(tmp_path, _artifact())
    monkeypatch.setattr(C, "CALIBRATION_FILE", path)
    monkeypatch.setattr(C.settings, "calibration_sha256", None, raising=False)
    C.reload_for_tests()
    assert C.calibrate("rule", 0.5).calibrated is True
    assert C.status()["state"] == "unverified"


def test_missing_file_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CALIBRATION_FILE", tmp_path / "nope.json")
    monkeypatch.setattr(C.settings, "calibration_sha256", "a" * 64, raising=False)
    C.reload_for_tests()
    assert C.calibrate("rule", 0.5).calibrated is False
    assert C.status()["state"] == "missing"


# ══════════════════════════════════════════════════════════════════════════════
# 2. ตรวจตอน start
# ══════════════════════════════════════════════════════════════════════════════


def test_startup_passes_when_everything_matches(tmp_path):
    path, sha = _write(tmp_path, _artifact())
    C.validate_startup(_settings(path, sha))


def test_shadow_hybrid_without_table_refuses_to_start():
    with pytest.raises(RuntimeError, match="shadow_hybrid"):
        C.validate_startup(_settings(None, None))


def test_shadow_mode_without_table_still_starts():
    """พฤติกรรมเดิมของโหมด shadow ต้องไม่เปลี่ยน — ยังไม่ calibrate ก็รันได้."""
    C.validate_startup(_settings(None, None, l3_mode="shadow"))


@pytest.mark.parametrize("mode", ["shadow", "shadow_hybrid", "monitor_only", "off"])
def test_configured_path_requires_expected_hash_in_every_mode(tmp_path, mode):
    path, _ = _write(tmp_path, _artifact())
    with pytest.raises(RuntimeError, match="CALIBRATION_SHA256"):
        C.validate_startup(_settings(path, None, l3_mode=mode))


def test_configured_path_missing_file_refuses(tmp_path):
    with pytest.raises(RuntimeError, match="ไม่พบ"):
        C.validate_startup(
            _settings(tmp_path / "gone.json", "a" * 64, l3_mode="shadow")
        )


def test_hash_mismatch_refuses(tmp_path):
    path, _ = _write(tmp_path, _artifact())
    with pytest.raises(RuntimeError, match="sha256"):
        C.validate_startup(_settings(path, "b" * 64))


def test_version_mismatch_refuses(tmp_path):
    path, sha = _write(tmp_path, _artifact())
    with pytest.raises(RuntimeError, match="version"):
        C.validate_startup(_settings(path, sha, calibration_version="other-v9"))


@pytest.mark.parametrize(
    "field, value",
    [
        ("l4_threshold_warn", 0.50),
        ("l4_threshold_challenge", 0.70),
        ("l4_threshold_block", 0.85),
    ],
)
def test_thresholds_not_from_this_table_refuse(tmp_path, field, value):
    """หลักฐานเป็นเปอร์เซ็นไทล์แต่เกณฑ์เป็นชุดเก่า = block เกือบทุกครั้ง ต้องไม่ยอม start."""
    path, sha = _write(tmp_path, _artifact())
    with pytest.raises(RuntimeError, match="threshold"):
        C.validate_startup(_settings(path, sha, l3_mode="shadow", **{field: value}))


def test_gamma_not_from_this_table_refuses(tmp_path):
    path, sha = _write(tmp_path, _artifact())
    with pytest.raises(RuntimeError, match="gamma"):
        C.validate_startup(_settings(path, sha, l4_gamma=0.35))


def test_table_without_derived_thresholds_refuses(tmp_path):
    """ตรวจไม่ได้ว่าเกณฑ์มาจากตารางนี้ = ถือว่าไม่ตรง."""
    art = _artifact()
    del art["derived_thresholds"]
    path, sha = _write(tmp_path, art)
    with pytest.raises(RuntimeError, match="derived_thresholds"):
        C.validate_startup(_settings(path, sha))


def test_startup_is_wired_into_app_lifespan():
    """ตรวจตอน start ต้องถูกเรียกจริง — ฟังก์ชันที่ไม่มีใครเรียกคือ B70."""
    from pathlib import Path

    src = (Path(C.__file__).resolve().parents[1] / "main.py").read_text(
        encoding="utf-8"
    )
    assert "validate_startup(" in src


# ══════════════════════════════════════════════════════════════════════════════
# 3. ตัวสร้างต้องบันทึก gamma ไว้ในไฟล์ด้วย
# ══════════════════════════════════════════════════════════════════════════════


def test_builder_records_fusion_parameters():
    core = pytest.importorskip("scripts.calibration_core")
    grids = {
        layer: core.quantile_grid([i / 1000 for i in range(2000)], n=1000)
        for layer in core.LAYERS
    }
    art = core.build_artifact(
        version="v",
        grids=grids,
        final_scores=[i / 20000 for i in range(20000)],
        percentiles={"warn": 0.95, "challenge": 0.99, "block": 0.999},
        gamma=0.8,
        source={},
        normal_definition="test",
    )
    assert art["fusion"]["gamma"] == 0.8
    assert art["fusion"]["config"] == "B"
