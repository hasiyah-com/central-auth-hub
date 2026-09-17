"""Functional Gate กับ Performance Gate ต้องแยกกันจริงในโค้ด ไม่ใช่แค่ตกลงกันด้วยปาก.

ที่มา: `test_concurrent_requests_agree` ล้มหลัง Docker restart (สำเร็จ 9/20) ทั้งที่ไม่มี
race · สาเหตุคือ ml-service ประมวลผล L3 ต่อคิว ยิง 20 ตัวพร้อมกัน p50 ราว 530–630 ms
เกิน timeout 500 ms · เงื่อนไข "สำเร็จ >= 18/20" จึงวัดความเร็วของเครื่อง ไม่ได้วัด race
ทำให้ Functional Gate ขึ้นกับความเร็ว ซึ่งขัดกับที่ตัดสินไว้ว่าให้แยกสองเกตออกจากกัน

เทสไฟล์นี้อ่านซอร์สแล้วยืนยันว่าเทสแต่ละตัวอยู่ถูกเกต
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent

# (ไฟล์, ชื่อเทส) ที่ต้องอยู่ใน Performance Gate
PERFORMANCE = {
    ("test_l3_explainability.py", "test_latency_within_login_budget"),
    ("test_l3_stability.py", "test_latency_within_login_budget"),
    ("test_l3_explainability.py", "test_concurrent_burst_mostly_within_timeout"),
}
# ต้องอยู่ใน Functional Gate — ห้ามติด marker performance
FUNCTIONAL = {
    ("test_l3_explainability.py", "test_concurrent_requests_agree"),
}


def _markers(filename: str) -> dict[str, set[str]]:
    tree = ast.parse((TESTS / filename).read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = set()
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                if isinstance(target, ast.Attribute):
                    names.add(target.attr)
            out[node.name] = names
    return out


def test_performance_marker_is_registered():
    """--strict-markers เปิดอยู่ ถ้าไม่ลงทะเบียน marker เทสจะล้มตอน collect."""
    ini = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    assert "performance:" in ini


def test_latency_and_burst_tests_are_in_performance_gate():
    missing = []
    for filename, name in sorted(PERFORMANCE):
        marks = _markers(filename)
        assert name in marks, f"ไม่พบ {filename}::{name}"
        if "performance" not in marks[name]:
            missing.append(f"{filename}::{name}")
    assert not missing, f"ยังไม่อยู่ใน Performance Gate: {missing}"


def test_race_test_stays_in_functional_gate():
    for filename, name in sorted(FUNCTIONAL):
        marks = _markers(filename)
        assert name in marks, f"ไม่พบ {filename}::{name}"
        assert "performance" not in marks[name], f"{name} ต้องอยู่ใน Functional Gate"


def test_race_test_does_not_depend_on_login_timeout():
    """เทส race ต้องขยาย timeout เอง — ไม่งั้นผลขึ้นกับความเร็วของเครื่องอีก."""
    src = (TESTS / "test_l3_explainability.py").read_text(encoding="utf-8")
    start = src.index("async def test_concurrent_requests_agree")
    ends = [
        i
        for i in (src.find("\n@pytest", start), src.find("\nasync def ", start + 10))
        if i > 0
    ]
    body = src[start : min(ends) if ends else len(src)]
    assert "l3_timeout_seconds" in body, "ต้อง monkeypatch l3_timeout_seconds ในเทสนี้"
    assert "== 20" in body, "เมื่อไม่ผูกกับเวลาแล้ว ต้องสำเร็จครบทุก request"


def test_run_tests_defaults_to_functional_gate():
    import pytest

    # host: <repo>/hub/backend -> <repo>/scripts · คอนเทนเนอร์: /app มี parent ชั้นเดียว
    parents = ROOT.parents
    path = (parents[1] if len(parents) > 1 else ROOT) / "scripts/test/run_tests.sh"
    if not path.exists():
        pytest.skip("scripts/test ไม่ได้ mount ในคอนเทนเนอร์ — ตรวจบน host")
    script = path.read_text(encoding="utf-8")
    assert "TEST_GATE" in script
    assert "not performance" in script
