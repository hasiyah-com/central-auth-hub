"""ขั้นที่ 3 — เทียบ distribution ของ traffic จริงกับประชากรจำลอง P48.

**เป็น descriptive / exploratory เท่านั้น ห้ามใช้เป็น deployment gate**
ผู้ใช้จริงมีน้อยมาก (2 คนที่มี IP ภายนอก) จึงตอบได้แค่ว่า "อยู่ในช่วงของ P48 ไหม"
ไม่ใช่ "P48 สมจริงหรือไม่" ในเชิงสถิติ

**หลักการสำคัญ:** สถิติทั้งสองฝั่งคำนวณด้วย `user_stats()` ตัวเดียวกันเป๊ะ
ถ้าคำนวณคนละทางจะแยกไม่ออกว่าความต่างมาจากประชากรหรือมาจากวิธีวัด (บทเรียน B66)

**สอง stratum ที่รายงานแยกกัน** (ไม่รวมกันเพราะที่มาต่างกันสิ้นเชิง):

    external   IP ภายนอกจริง — ใกล้เคียง production ที่สุด แต่เล็กมาก
    local      IP ภายในเครื่อง/Docker — ส่วนใหญ่เป็น traffic ของนักพัฒนา
               **ระบุที่มาไม่ได้** อาจเป็น login จริงผ่าน proxy ที่ไม่ตั้ง X-Forwarded-For

แถวที่มี marker `RiskDemo` หรือ IP ตาม RFC 5737 ถูกตัดออกทั้งหมด

    python exp_real_vs_p48_distribution.py
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ML = Path(__file__).resolve().parent
if str(ML) not in sys.path:
    sys.path.insert(0, str(ML))

import build_profiles_v2 as BP  # noqa: E402
import gen_v3 as G3  # noqa: E402
import population_p48 as P48  # noqa: E402

# marker ของข้อมูล demo — ต้องตรงกับ scripts/evaluate_real_logins.py
SYNTHETIC_UA_MARKERS = ("RiskDemo",)
RFC5737 = ("192.0.2.", "203.0.113.", "198.51.100.")


# ══════════════ สถิติต่อผู้ใช้ — ใช้ร่วมกันทั้งสองฝั่ง ══════════════
def user_stats(events: list[dict]) -> dict | None:
    """สถิติเชิงสังเกตของผู้ใช้หนึ่งคน จาก event ที่ normalize แล้ว.

    event ต้องมีคีย์: ts (datetime), device (str|None), subsystem (str|None),
    duration_min (float|None), method (str|None)

    คืน None ถ้าเหตุการณ์น้อยเกินกว่าจะคำนวณได้ (ต้องมีอย่างน้อย 2 เพื่อหา cadence)
    """
    if len(events) < 2:
        return None
    ev = sorted(events, key=lambda e: e["ts"])
    ts = [e["ts"] for e in ev]

    days = {t.date() for t in ts}
    span_days = max(1, (ts[-1].date() - ts[0].date()).days + 1)

    hours = Counter(t.hour for t in ts)
    # "โหมดเวลา" = ชั่วโมงที่มีสัดส่วนอย่างน้อย 15% ของการใช้งานทั้งหมด
    n_time_modes = sum(1 for _, c in hours.items() if c / len(ts) >= 0.15)

    devices = Counter(e["device"] for e in ev if e["device"])
    subs = Counter(e["subsystem"] or "HUB" for e in ev)
    methods = Counter(e["method"] for e in ev if e["method"])

    gaps = [
        (b - a).total_seconds() / 60.0
        for a, b in zip(ts, ts[1:])
        if (b - a).total_seconds() > 0
    ]
    durs = [e["duration_min"] for e in ev if e["duration_min"] is not None]

    def share(c: Counter, which: str) -> float | None:
        if not c:
            return None
        vals = sorted(c.values(), reverse=True)
        tot = sum(vals)
        if which == "top":
            return vals[0] / tot
        return (vals[1] / tot) if len(vals) > 1 else 0.0

    return {
        "n_events": len(ev),
        "active_days": len(days),
        "span_days": span_days,
        "logins_per_active_day": round(len(ts) / len(days), 4),
        "n_time_modes": n_time_modes,
        "peak_hour": hours.most_common(1)[0][0],
        "weekend_rate": round(sum(1 for t in ts if t.weekday() >= 5) / len(ts), 4),
        "n_devices": len(devices),
        "device_top_share": round(share(devices, "top"), 4) if devices else None,
        "device_second_share": round(share(devices, "second"), 4) if devices else None,
        "n_subsystems": len(subs),
        "subsystem_top_share": round(share(subs, "top"), 4),
        "subsystem_second_share": round(share(subs, "second"), 4),
        "median_gap_min": round(statistics.median(gaps), 2) if gaps else None,
        "median_duration_min": round(statistics.median(durs), 2) if durs else None,
        "n_methods": len(methods),
        "passkey_share": round(
            sum(v for k, v in methods.items() if k and "passkey" in k.lower())
            / max(1, sum(methods.values())),
            4,
        ),
    }


def summarize(stats: list[dict], field: str) -> dict | None:
    """median / IQR / min-max ของฟิลด์หนึ่งข้ามผู้ใช้ — คำนวณต่อผู้ใช้ก่อนเสมอ."""
    vals = [s[field] for s in stats if s.get(field) is not None]
    if not vals:
        return None
    vals = sorted(vals)

    def q(p: float) -> float:
        return vals[min(len(vals) - 1, int(p * len(vals)))]

    return {
        "n_users": len(vals),
        "min": round(vals[0], 4),
        "q25": round(q(0.25), 4),
        "median": round(q(0.50), 4),
        "q75": round(q(0.75), 4),
        "max": round(vals[-1], 4),
    }


def coverage(real: list[dict], ref: list[dict], field: str) -> dict | None:
    """ผู้ใช้จริงกี่คนอยู่นอกช่วง min-max ของ P48."""
    rv = [s[field] for s in real if s.get(field) is not None]
    fv = [s[field] for s in ref if s.get(field) is not None]
    if not rv or not fv:
        return None
    lo, hi = min(fv), max(fv)
    outside = [round(v, 4) for v in rv if v < lo or v > hi]
    return {
        "p48_range": [round(lo, 4), round(hi, 4)],
        "n_real": len(rv),
        "n_outside": len(outside),
        "outside_values": outside[:10],
        "inside": len(outside) == 0,
    }


# ══════════════ ฝั่งข้อมูลจริง ══════════════
def _psql(sql: str) -> list[list[str]]:
    """อ่านผ่าน docker compose exec — ไม่ต้องมี driver ฝั่ง host."""
    out = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "hub",
            "-d",
            "hub_db",
            "-A",
            "-F",
            "\t",
            "-t",
            "-c",
            sql,
        ],
        cwd=ML.parent.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:400])
    return [ln.split("\t") for ln in out.stdout.splitlines() if ln.strip()]


def load_real() -> dict[str, list[dict]]:
    """ดึง login จริง แล้วแยกเป็นสอง stratum · ตัดข้อมูล demo ออกทั้งหมด."""
    rows = _psql(
        "SELECT user_id, created_at, COALESCE(host(ip),''), COALESCE(user_agent,''), "
        "COALESCE(device_type,'')||'|'||COALESCE(os_name,'')||'|'||COALESCE(browser,''), "
        "COALESCE(subsystem_id::text,''), COALESCE(login_method,''), "
        "COALESCE(EXTRACT(epoch FROM (logout_at - created_at))/60.0, -1)::numeric(10,2) "
        "FROM login_sessions ORDER BY created_at;"
    )
    strata: dict[str, dict[str, list[dict]]] = {
        "external": defaultdict(list),
        "local": defaultdict(list),
    }
    dropped = 0
    for uid, ts, ip, ua, dev, sub, method, dur in rows:
        if any(m in ua for m in SYNTHETIC_UA_MARKERS) or any(
            ip.startswith(p) for p in RFC5737
        ):
            dropped += 1
            continue
        is_local = (
            ip.startswith("127.")
            or ip.startswith("172.1")
            or ip.startswith("172.2")
            or ip.startswith("172.3")
            or ip.startswith("192.168.")
            or ip in ("", "::1")
        )
        # browser family เท่านั้น — เลขเวอร์ชันเปลี่ยนไม่ควรนับเป็นเครื่องใหม่ (B56)
        d, o, b = (dev.split("|") + ["", "", ""])[:3]
        sig = f"{d}|{o}|{b.split()[0] if b else ''}" if any((d, o, b)) else None
        strata["local" if is_local else "external"][uid].append(
            {
                "ts": datetime.fromisoformat(ts),
                "device": sig,
                "subsystem": sub or None,
                "duration_min": (float(dur) if float(dur) >= 0 else None),
                "method": method or None,
            }
        )
    print(f"  ตัดข้อมูล demo ออก {dropped} แถว")
    return {k: dict(v) for k, v in strata.items()}


# ══════════════ ฝั่ง P48 ══════════════
def load_p48(users_xlsx: Path, seed: int) -> dict[str, list[dict]]:
    """สร้างเหตุการณ์ของ P48-validation แล้ว normalize ให้อยู่รูปเดียวกับข้อมูลจริง."""
    roster_path = BP.DATA / "roster_p48.json"
    roster = json.loads(roster_path.read_text(encoding="utf-8"))
    val, _ = P48.split_population(P48.generate_population())
    raw = G3.build_seed(users_xlsx, seed, spec=val, roster=roster)
    out: dict[str, list[dict]] = {}
    for alias, u in raw.items():
        evs = []
        for r in u["train_raw"]:
            evs.append(
                {
                    "ts": datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S"),
                    "device": r.get("device_signature"),
                    "subsystem": r.get("subsystem"),
                    "duration_min": r.get("duration_min"),
                    "method": r.get("login_method"),
                }
            )
        out[alias] = evs
    return out


# ══════════════ รายงาน ══════════════
FIELDS = [
    ("logins_per_active_day", "login ต่อวันที่ใช้งาน"),
    ("active_days", "จำนวนวันที่ใช้งาน"),
    ("n_time_modes", "จำนวนโหมดเวลา"),
    ("peak_hour", "ชั่วโมงที่ใช้มากสุด"),
    ("weekend_rate", "สัดส่วนวันหยุด"),
    ("n_devices", "จำนวนอุปกรณ์"),
    ("device_top_share", "สัดส่วนอุปกรณ์หลัก"),
    ("device_second_share", "สัดส่วนอุปกรณ์รอง"),
    ("n_subsystems", "จำนวน subsystem"),
    ("subsystem_top_share", "สัดส่วน subsystem หลัก"),
    ("subsystem_second_share", "สัดส่วน subsystem รอง"),
    ("median_gap_min", "ระยะห่างระหว่าง login (นาที)"),
    ("median_duration_min", "ความยาว session (นาที)"),
    ("n_methods", "จำนวนวิธี login"),
    ("passkey_share", "สัดส่วนการใช้ passkey"),
]


def run(args) -> int:
    print("REAL vs P48 — descriptive coverage analysis")
    print("  ไม่ใช่ deployment gate · ผู้ใช้จริงน้อยเกินกว่าจะสรุปเชิงสถิติ\n")

    real = load_real()
    p48_events = load_p48(args.users, args.seed)

    p48_stats = [s for s in (user_stats(e) for e in p48_events.values()) if s]
    print(f"  P48-validation: {len(p48_stats)} โปรไฟล์ (seed {args.seed})")

    result: dict = {
        "note": (
            "descriptive/exploratory เท่านั้น · ห้ามใช้เป็น deployment gate · "
            "สถิติทั้งสองฝั่งคำนวณด้วย user_stats() ตัวเดียวกัน"
        ),
        "p48": {"n_users": len(p48_stats), "seed": args.seed},
        "strata": {},
    }

    for name, users in real.items():
        stats = [s for s in (user_stats(e) for e in users.values()) if s]
        conc = None
        if stats:
            tot = sum(s["n_events"] for s in stats)
            top = max(s["n_events"] for s in stats)
            conc = round(top / tot, 4)
        print(
            f"  stratum {name:9}: {len(stats)} ผู้ใช้ที่คำนวณได้ "
            f"(จาก {len(users)} คน) · ความกระจุกตัวสูงสุด "
            f"{f'{conc:.1%}' if conc else '-'}"
        )
        result["strata"][name] = {
            "n_users_raw": len(users),
            "n_users_usable": len(stats),
            "top_user_event_share": conc,
            "fields": {
                f: {
                    "real": summarize(stats, f),
                    "p48": summarize(p48_stats, f),
                    "coverage": coverage(stats, p48_stats, f),
                }
                for f, _ in FIELDS
            },
        }

    args.out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    _print(result)
    print(f"\nเขียนผลลง {args.out}")
    return 0


def _print(res: dict) -> None:
    for name, s in res["strata"].items():
        if not s["n_users_usable"]:
            print(f"\n=== stratum {name}: ไม่มีผู้ใช้ที่คำนวณสถิติได้ ===")
            continue
        print(
            f"\n=== stratum {name} · {s['n_users_usable']} ผู้ใช้ "
            f"(P48 = {res['p48']['n_users']}) ==="
        )
        print(
            f"{'ตัวชี้วัด':30}{'จริง median':>14}{'P48 median':>13}"
            f"{'ช่วง P48':>22}{'นอกช่วง':>10}"
        )
        for f, label in FIELDS:
            d = s["fields"][f]
            r, p, c = d["real"], d["p48"], d["coverage"]
            if not r or not p:
                continue
            rng = f"[{c['p48_range'][0]}, {c['p48_range'][1]}]" if c else "-"
            out = f"{c['n_outside']}/{c['n_real']}" if c else "-"
            print(f"{label:30}{r['median']:>14}{p['median']:>13}{rng:>22}{out:>10}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    ap.add_argument("--seed", type=int, default=301)
    ap.add_argument(
        "--out",
        type=Path,
        default=BP.DATA / "hybrid_experiment" / "real_vs_p48_distribution.json",
    )
    return run(ap.parse_args())


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    raise SystemExit(main())
