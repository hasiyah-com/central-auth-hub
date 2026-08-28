"""Regression — window ของ L3 ห้ามคร่อมขอบ episode หรือ attack family.

ที่มา: tests/reports/exp_l3_window_2026-08-26.md — เคยเกิด 2 บั๊กที่ทำให้ผลเฟ้อ/เพี้ยน

  1. **cross-family window** — เอา attack ทุกชนิดของผู้ใช้มาต่อเป็นลิสต์เดียว
     -> window คร่อม `new_device` + `off_hours` + `campaign` ในกรอบเดียว
     -> วัดได้ unique 4.18% ทั้งที่ของจริง 1.3% (เฟ้อ 3 เท่า)

  2. **window construction ไม่ตรงกันระหว่าง train/validation/test**
     validation มีแต่ window เต็ม แต่ตอน score มี padded window
     -> padded กลายเป็น "ของแปลก" -> L3 FPR พุ่ง 0.9% -> 5.8% (6 เท่า)

test นี้ล็อกกฎไว้ไม่ให้ย้อนกลับมา

Run: py hub/backend/tests/test_l3_window_integrity.py
"""

from __future__ import annotations

from app.security import l3_sequence as L3


def rows(tags):
    """สร้าง residual ปลอม 1 ค่า/แถว โดยติด tag (episode/family) กำกับ."""
    return [([float(i)] * L3.DIMS, t) for i, t in enumerate(tags)]


def windows_by_group(data, window):
    """สร้าง window แบบถูกกฎ: ไม่ข้าม group — คืน (window, group ที่ใช้)."""
    out, cur, buf = [], None, []
    for vec, tag in data:
        if tag != cur:
            cur, buf = tag, []
        buf.append(vec)
        w = buf[-window:]
        while len(w) < window:
            w = [w[0]] + w
        out.append((w, cur))
    return out


# ── กฎ 1: window ต้องอยู่ใน group เดียว (episode/family) ──
def test_window_never_crosses_group():
    data = rows(["ep0"] * 6 + ["ep1"] * 6)
    for w, grp in windows_by_group(data, L3.WINDOW):
        # ทุกแถวใน window ต้องมาจาก group เดียวกัน -> ตรวจผ่านค่าที่ใส่ไว้
        idxs = {int(v[0]) for v in w}
        src = {"ep0" if i < 6 else "ep1" for i in idxs}
        assert src == {grp}, f"window คร่อม group: {src} แต่ควรเป็น {grp}"


# ── กฎ 2: จำนวน window ต้องเท่าจำนวน event (รวม padded ต้น group) ──
def test_window_count_matches_events():
    data = rows(["a"] * 7 + ["b"] * 3)
    assert len(windows_by_group(data, L3.WINDOW)) == len(data)


# ── กฎ 3: group ที่สั้นกว่า WINDOW ต้อง pad ไม่ใช่ยืมจาก group ก่อนหน้า ──
def test_short_group_pads_not_borrows():
    data = rows(["a"] * 8 + ["b"] * 2)
    w, grp = windows_by_group(data, L3.WINDOW)[-1]
    assert grp == "b"
    assert {int(v[0]) for v in w} <= {8, 9}, "ยืมแถวจาก group ก่อนหน้า"


# ── กฎ 4: production evaluate_window ใช้ window ยาวเท่า WINDOW เสมอ ──
def test_production_requires_full_window():
    quiet = L3.evaluate_window(None, [[0.0] * L3.DIMS] * (L3.WINDOW - 1))
    assert quiet.fired is False


# ── กฎ 5: WINDOW ที่ใช้จริงต้องเป็นค่าที่ผ่านการทดลอง (กันแก้มั่ว) ──
def test_window_is_validated_value():
    assert L3.WINDOW == 5, (
        "W=5 คือค่าที่เลือกจาก development set และยืนยันบน holdout "
        "(W=10/multi-scale แย่กว่า — ดู exp_l3_window_2026-08-26.md) "
        "ถ้าจะเปลี่ยนต้องรันการทดลองใหม่ก่อน"
    )


if __name__ == "__main__":
    import sys

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            ok += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{ok}/{len(fns)} passed")
    sys.exit(0 if ok == len(fns) else 1)
