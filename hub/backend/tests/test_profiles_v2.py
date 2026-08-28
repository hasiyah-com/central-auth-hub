"""ตรวจสอบชุดข้อมูลโปรไฟล์ V2 ว่าตรงกับ blueprint จริง.

blueprint: hub/backend/tests/reports/user_profile_blueprint_v2_2026-08-21.md
generator: ml-service/scripts/build_profiles_v2.py

ตรวจ 12 ข้อ: ข้อจำกัด (IP/geo), ปริมาณ, พฤติกรรมต่อคน, ความถูกต้องของ attack

Run:
    py -m pytest hub/backend/tests/test_profiles_v2.py -v
    py hub/backend/tests/test_profiles_v2.py          # โหมดรายงาน (ไม่ต้องมี pytest)
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# host-only: ชุดนี้อ่าน ml-service/data ของ repo (ไม่ได้ mount เข้า container)
# ใน docker (WORKDIR=/app) จึงไม่มี parents[3] -> skip ทั้งไฟล์แทนที่จะ error ตอน collect
_p = Path(__file__).resolve()
ROOT = _p.parents[3] if len(_p.parents) > 3 else None
if ROOT is None or not (ROOT / "ml-service" / "data").exists():
    import pytest

    pytest.skip("ต้องรันบน host (ใช้ ml-service/data ของ repo)", allow_module_level=True)
DATA = ROOT / "ml-service" / "data"

EXPECTED_ROWS = {
    "U01": 100,
    "U02": 78,
    "U03": 60,
    "U04": 66,
    "U05": 78,
    "U06": 72,
    "U07": 66,
    "U08": 99,
    "U09": 72,
    "U10": 78,
    "U11": 84,
    "U12": 75,
}
SCENARIOS = {
    "combined_ato",
    "new_device",
    "new_ua_family",
    "new_os",
    "off_hours",
    "failed_spike",
    "login_velocity",
    "concurrent_sessions",
    "new_passkey",
    "permission_change",
    "subsystem_lateral",
}


def hour_gap(h: int, peaks: list[int]) -> int:
    """ระยะห่างจาก peak แบบนาฬิกาวนรอบ (00:00 ห่างจาก 22:00 = 2 ชม. ไม่ใช่ 22)."""
    return min(min(abs(h - q) % 24, 24 - abs(h - q) % 24) for q in peaks)


def _load():
    logins = list(csv.DictReader(open(DATA / "logins_v2.csv", encoding="utf-8")))
    attacks = list(csv.DictReader(open(DATA / "attacks_v2.csv", encoding="utf-8")))
    prof = json.load(open(DATA / "profiles_v2.json", encoding="utf-8"))
    return logins, attacks, prof


def test_ip_constant_and_no_geo():
    """ข้อจำกัดหลัก: IP เดียวทุกแถว และไม่มี geo เลย."""
    logins, attacks, _ = _load()
    for rows, name in ((logins, "logins"), (attacks, "attacks")):
        ips = {r["ip"] for r in rows}
        assert ips == {"192.168.10.1"}, f"{name}: IP ไม่คงที่ -> {ips}"
        assert not any(
            r["geo_country"] or r["geo_city"] for r in rows
        ), f"{name}: มี geo หลุดมา"


def test_row_counts_in_60_100_band():
    """60-100 แถว/คน ต่อ 1 condition ตามที่ตกลง."""
    logins, _, _ = _load()
    per = defaultdict(Counter)
    for r in logins:
        per[r["alias"]][r["normal_condition"]] += 1
    assert set(per) == set(EXPECTED_ROWS), "จำนวนผู้ใช้ไม่ครบ 12"
    for alias, conds in per.items():
        assert set(conds) == {
            "staggered",
            "nat_burst",
        }, f"{alias}: condition ไม่ครบ 2 แบบ"
        for cond, n in conds.items():
            assert (
                n == EXPECTED_ROWS[alias]
            ), f"{alias}/{cond}: ได้ {n} ต้องการ {EXPECTED_ROWS[alias]}"
            assert 60 <= n <= 100, f"{alias}/{cond}: {n} หลุดกรอบ 60-100"


def test_window_is_30_days():
    """ทุกเหตุการณ์อยู่ในช่วง 2026-07-22 .. 2026-08-21."""
    logins, attacks, _ = _load()
    lo, hi = datetime(2026, 7, 22), datetime(2026, 8, 22)
    for r in logins + attacks:
        t = datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S")
        assert lo <= t < hi, f"{r['alias']} {r['scenario']}: {t} หลุดช่วง"


def test_nat_burst_concentrates_on_campus_peaks():
    """nat_burst ต้องกระจุกที่ชั่วโมง peak ร่วม มากกว่า staggered อย่างมีนัย."""
    logins, _, _ = _load()
    peak = {8, 9, 13, 16}
    share = {}
    for cond in ("staggered", "nat_burst"):
        rows = [r for r in logins if r["normal_condition"] == cond]
        hit = sum(
            1
            for r in rows
            if datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S").hour in peak
        )
        share[cond] = hit / len(rows)
    assert (
        share["nat_burst"] > share["staggered"] + 0.15
    ), f"burst ไม่กระจุกจริง: staggered {share['staggered']:.1%} vs nat_burst {share['nat_burst']:.1%}"


def test_browser_drift_keeps_device_signature_stable():
    """B56: browser version drift ต้องไม่สร้าง device signature ใหม่."""
    logins, _, prof = _load()
    per = defaultdict(set)
    for r in logins:
        per[r["alias"]].add(r["device_signature"])
    for alias, sigs in per.items():
        declared = set(prof["profiles"][alias]["device_signatures"])
        assert sigs == declared, f"{alias}: signature ที่พบ {sigs} != ประกาศไว้ {declared}"
    # ต้องมีอย่างน้อย 1 คนที่ browser หลายเวอร์ชันแต่ signature เดียว
    multi = [
        a
        for a in per
        if per[a]
        and any(
            len(
                {
                    r["browser"]
                    for r in logins
                    if r["alias"] == a and r["device_signature"] == s
                }
            )
            > 1
            for s in per[a]
        )
    ]
    assert multi, "ไม่พบ version drift เลย — knob drift ไม่ทำงาน"


def test_attack_count_is_20_per_user():
    """20 attack แถว/คน × 12 = 240 (context ไม่นับ)."""
    _, attacks, _ = _load()
    per = Counter(r["alias"] for r in attacks if r["row_kind"] == "attack")
    assert len(per) == 12, f"attack ไม่ครบ 12 คน: {len(per)}"
    for alias, n in per.items():
        assert n == 20, f"{alias}: attack {n} แถว (ต้อง 20)"
    assert sum(per.values()) == 240


def test_all_scenarios_present_per_user():
    """ทุกคนต้องมีครบ 11 scenario และไม่มี geo-based scenario หลุดเข้ามา."""
    _, attacks, _ = _load()
    per = defaultdict(set)
    for r in attacks:
        if r["row_kind"] == "attack":
            per[r["alias"]].add(r["scenario"])
    for alias, sc in per.items():
        assert sc == SCENARIOS, f"{alias}: scenario ขาด/เกิน -> {sc ^ SCENARIOS}"
    banned = {"impossible_travel", "new_country"}
    assert not any(r["scenario"] in banned for r in attacks), "มี geo scenario หลุดมา"


def test_new_device_uses_unseen_signature():
    """new_device / new_ua_family / combined_ato ต้องใช้ signature ที่คนนั้นไม่เคยใช้."""
    _, attacks, prof = _load()
    for r in attacks:
        if r["scenario"] in ("new_device", "new_ua_family", "combined_ato"):
            own = set(prof["profiles"][r["alias"]]["device_signatures"])
            assert (
                r["device_signature"] not in own
            ), f"{r['alias']} {r['scenario']}: ใช้เครื่องเดิม {r['device_signature']}"


def test_off_hours_is_personalized():
    """off_hours ต้องห่างจาก peak ของ 'คนนั้น' >= 6 ชม. โดยวัดแบบนาฬิกาวนรอบ."""
    _, attacks, prof = _load()
    checked = 0
    for r in attacks:
        if r["scenario"] in ("off_hours", "combined_ato") and r["row_kind"] == "attack":
            peaks = prof["profiles"][r["alias"]]["knobs"]["hour_peaks"]
            h = datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S").hour
            gap = hour_gap(h, peaks)
            assert (
                gap >= 6
            ), f"{r['alias']}: off_hours {h} ห่าง peak {peaks} แค่ {gap} ชม. (วนรอบ)"
            checked += 1
    assert checked == 48, f"off_hours(24) + combined_ato(24) = 48 แถว ได้ {checked}"


def test_normal_data_has_no_failed_spike():
    """ข้อมูล normal ต้องไม่มี failed login >=5 ครั้งใน 1 ชม. — ไม่งั้น label 0 ปนสัญญาณ attack."""
    logins, _, _ = _load()
    by_user = defaultdict(list)
    for r in logins:
        if r["login_successful"] == "False":
            key = (r["alias"], r["normal_condition"])
            by_user[key].append(datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S"))
    for key, ts in by_user.items():
        ts.sort()
        for i in range(len(ts)):
            n = sum(1 for t in ts[i:] if (t - ts[i]).total_seconds() <= 3600)
            assert (
                n < 5
            ), f"{key}: fail {n} ครั้งใน 1 ชม. ที่ {ts[i]} — normal ปนสัญญาณ brute force"


def test_normal_data_has_no_velocity_burst():
    """ข้อมูล normal ต้องไม่มี success >=4 ครั้งใน 10 นาที — กันชนกับ scenario login_velocity."""
    logins, _, _ = _load()
    by_user = defaultdict(list)
    for r in logins:
        if r["login_successful"] == "True":
            key = (r["alias"], r["normal_condition"])
            by_user[key].append(datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S"))
    for key, ts in by_user.items():
        ts.sort()
        for i in range(len(ts)):
            n = sum(1 for t in ts[i:] if (t - ts[i]).total_seconds() <= 600)
            assert (
                n < 4
            ), f"{key}: success {n} ครั้งใน 10 นาที ที่ {ts[i]} — normal ปนสัญญาณ velocity"


def test_u07_off_hours_differs_from_others():
    """U07 (ปกติตี 4-6) ต้องได้ off_hours คนละช่วงกับคนกลางวัน — พิสูจน์ personalization."""
    _, attacks, _ = _load()
    hours = defaultdict(set)
    for r in attacks:
        if r["scenario"] == "off_hours" and r["row_kind"] == "attack":
            hours[r["alias"]].add(
                datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S").hour
            )
    assert hours["U07"] and hours["U01"], "ไม่มีข้อมูล off_hours ของ U07/U01"
    assert (
        hours["U07"] != hours["U01"]
    ), f"off_hours ไม่ personalize: U07={hours['U07']} เท่ากับ U01={hours['U01']}"


def test_context_rows_support_their_scenario():
    """scenario ที่ต้องมี pre-condition ต้องมี context rows จริง."""
    _, attacks, _ = _load()
    ctx = Counter(r["scenario"] for r in attacks if r["row_kind"] == "context")
    for sc in ("failed_spike", "login_velocity", "concurrent_sessions", "combined_ato"):
        assert ctx[sc] > 0, f"{sc}: ไม่มี context rows"
    fails = [
        r
        for r in attacks
        if r["scenario"] == "failed_spike" and r["row_kind"] == "context"
    ]
    assert all(
        r["login_successful"] == "False" for r in fails
    ), "failed_spike context ต้องเป็น login ล้มเหลว"


def test_lateral_targets_unused_subsystem():
    """subsystem_lateral ต้องเข้าระบบที่ผู้ใช้ไม่เคยใช้."""
    _, attacks, prof = _load()
    for r in attacks:
        if r["scenario"] == "subsystem_lateral" and r["row_kind"] == "attack":
            own = set(prof["profiles"][r["alias"]]["knobs"]["subsystems"])
            assert (
                r["subsystem"] not in own
            ), f"{r['alias']}: lateral ไปที่ {r['subsystem']} ซึ่งใช้ประจำ"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            ok += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}\n        {e}")
    print(f"\n{ok}/{len(fns)} passed")
