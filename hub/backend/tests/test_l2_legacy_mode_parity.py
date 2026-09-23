"""การตัด `min_action` (B70) ต้อง **ไม่เปลี่ยนคะแนน** ของ L2 เลยแม้แต่นิดเดียว.

ทำไมต้องมี: ฟิลด์นั้นถูกตัดออกด้วยเหตุผลว่า "ไม่เคยถูกอ่านบนเส้นทาง production"
ข้ออ้างนั้นต้องพิสูจน์ได้ด้วยตัวเลข ไม่ใช่การอ่านโค้ดแล้วเชื่อ

เทสเทียบ `evaluate_behavior` ปัจจุบันกับไฟล์เวอร์ชันก่อนแก้ที่ดึงจาก git โดยตรง
บน 400 เคสสุ่มที่ครอบคลุมทุกสาขาของตรรกะ (ถ้าไม่ได้อยู่ใน git working tree = skip)

เทสนี้ยังกันการแก้ตรรกะ L2 โดยไม่ตั้งใจระหว่างที่ scoring ถูก freeze ไว้เพื่อรอ
รอบทดลองชุดโปรไฟล์ผู้ใช้ใหม่ 40+ ด้วย

**ขอบเขต:** เทียบเฉพาะ `score` · ข้อความ `reasons` เปลี่ยนโดยตั้งใจ (ถอดคำว่า
"floor=challenge" ที่สื่อผิด) จึงไม่นำมาเทียบ

รัน: `docker compose exec hub-backend pytest tests/test_l2_legacy_mode_parity.py -v`
"""

from __future__ import annotations

import importlib.util
import random
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from app.security import behavior_profiling as BP
from app.security.rule_engine import FEAT

REL = "hub/backend/app/security/behavior_profiling.py"


def _load_pre_change_module():
    """ดึงไฟล์เวอร์ชันก่อนแก้จาก git แล้วโหลดเป็นโมดูลแยก."""
    here = Path(__file__).resolve()
    repo = next((p for p in here.parents if (p / ".git").exists()), None)
    if repo is None:
        pytest.skip("ไม่ได้อยู่ใน git working tree (ปกติเมื่อรันในคอนเทนเนอร์)")
    for rev in ("HEAD", "HEAD~1", "HEAD~2"):
        try:
            src = subprocess.run(
                ["git", "show", f"{rev}:{REL}"],
                cwd=repo,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except Exception:  # noqa: BLE001
            continue
        if "min_action: str | None = (" in src:
            break
    else:
        pytest.skip("หาเวอร์ชันก่อนแก้ใน git ไม่เจอ")

    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "old_behavior_profiling.py"
        f.write_text(src, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("old_behavior_profiling", f)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["old_behavior_profiling"] = mod
        spec.loader.exec_module(mod)
        return mod


N = max(FEAT.values()) + 1
SUBS = ("HUB", "SUB_A", "SUB_B")


def _cases(n=400, seed=20260906):
    """สุ่มโปรไฟล์+ฟีเจอร์ให้ครอบคลุมทุกสาขาของตรรกะเดิม."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        total = rng.choice([5, 19, 20, 50, 137, 500, 5000])
        seen = rng.sample(SUBS, rng.randint(1, 3))
        counts = {s: max(1, int(total * rng.random())) for s in seen}
        hist_n = rng.choice([0, 5, 19, 20, 200])
        profile = {
            "typical_hour": rng.randrange(24),
            "typical_weekend": rng.randint(0, 1),
            "session_count": total,
            "total": total,
            "hour_counts": {rng.randrange(24): rng.randint(1, total) for _ in range(4)},
            "subsystem_counts": counts,
            "seen_subsystems": set(counts),
            "gap_log_median": rng.uniform(2, 9),
            "gap_log_scale": rng.uniform(0.5, 3),
            "signature_counts": {"a": rng.randint(1, total), "b": rng.randint(1, 5)},
            "scope_history": [rng.choice([0.0, 0.2, 0.6, 0.8]) for _ in range(hist_n)],
        }
        v = [0.0] * N
        v[FEAT["hour_of_day"]] = float(rng.randrange(24))
        v[FEAT["day_of_week"]] = float(rng.randrange(7))
        v[FEAT["hours_from_typical_login_time"]] = rng.choice([0.0, 5.0, 7.0, 12.0])
        v[FEAT["is_new_country"]] = float(rng.randint(0, 1))
        v[FEAT["log_minutes_since_last_login"]] = rng.uniform(-2, 12)
        v[FEAT["scope_sensitivity_score"]] = rng.choice([0.0, 0.2, 0.6, 0.8, 1.0])
        out.append((v, profile, rng.choice(SUBS + (None,))))
    return out


def test_scores_match_pre_change_implementation():
    old = _load_pre_change_module()
    mismatches = []
    for v, profile, sub in _cases():
        a = BP.evaluate_behavior(v, dict(profile), subsystem_id=sub)
        b = old.evaluate_behavior(v, dict(profile), subsystem_id=sub)
        if abs(a.score - b.score) > 1e-12:
            mismatches.append((sub, a.score, b.score, a.reasons, b.reasons))
    assert not mismatches, f"{len(mismatches)} เคสไม่ตรง · ตัวอย่าง: {mismatches[:3]}"
