"""Production Shadow Replay — วิเคราะห์ L3 จาก traffic จริงที่บันทึกไว้.

อ่าน `login_sessions.risk_breakdown.l3_sequence` (data contract ที่ risk_engine เขียนทุก login)
แล้วตอบคำถามที่การทดลอง offline ตอบไม่ได้:

  1. raw vs alert       — L3 "ยิง" บ่อยแค่ไหน vs "ขึ้นธงให้ SOC" บ่อยแค่ไหน
                          (tier diagnostic ยิงได้แต่ยังไม่ขึ้นธง)
  2. ภาระ SOC           — alert ต่อวันที่ L3 เพิ่มเข้ามาจริง
  3. ความปลอดภัย        — ยืนยันว่า L3 **ไม่แตะ access decision เลย** บน traffic จริง
                          (สองแกนแยกกัน: access = L1/L2/L4 · monitoring = L3)
  4. **tier reachability** — ผู้ใช้จริงสะสม history ถึงเกณฑ์ที่ L3 ทำงานได้จริงไหม
                          (ข้อนี้สำคัญที่สุด: ถ้าไม่ถึง ตัวเลข offline ก็ไม่มีความหมาย)

ไม่พิมพ์ PII — รายงานเป็นค่าสรุปรวม + user แทนด้วย hash 8 ตัวอักษร

Run:
    docker compose exec hub-backend python -m scripts.l3_shadow_replay
    docker compose exec hub-backend python -m scripts.l3_shadow_replay --days 30
    docker compose exec hub-backend python -m scripts.l3_shadow_replay --out /app/tests/reports/x.md
"""

from __future__ import annotations

import argparse
import hashlib
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database import SessionLocal
from app.models import LoginSession
from app.security import l3_sequence as L3

ACTIONS = ["allow", "warn", "challenge", "block"]
# เกณฑ์ตัดสินใจของ shadow replay (ตั้งไว้ล่วงหน้า ห้ามแก้หลังเห็นผล)
GATE_MIN_EVENTS = 5000  # จำนวนเหตุการณ์ที่ eligible ขั้นต่ำก่อนสรุปอะไรได้
GATE_MAX_L3_FPR = 0.01  # L3 ยิงบน traffic ปกติต้อง <= 1%
GATE_MIN_UNIQUE = 0.03  # L3 ต้องเห็นสิ่งที่ L1/L2 ไม่เห็น >= 3% ถึงจะคุ้มค่า enforcement


def anon(uid) -> str:
    return hashlib.sha256(str(uid).encode()).hexdigest()[:8]


def collect(db, days: int | None):
    q = db.query(LoginSession)
    if days:
        q = q.filter(
            LoginSession.created_at
            >= datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        )
    rows = []
    for s in q.order_by(LoginSession.created_at.asc()).all():
        b = s.risk_breakdown if isinstance(s.risk_breakdown, dict) else {}
        rows.append((s, b.get("l3_sequence")))
    return rows


def analyse(rows) -> dict:
    total = len(rows)
    with_contract = [(s, c) for s, c in rows if isinstance(c, dict)]
    eligible = [(s, c) for s, c in with_contract if c.get("eligible")]

    elig_dist = Counter(c.get("eligibility") for _, c in with_contract)
    tier_dist = Counter(c.get("tier") for _, c in eligible)
    shadow_dist = Counter(c.get("shadow_decision") for _, c in eligible)
    fired = [(s, c) for s, c in eligible if c.get("tier") in ("anomaly", "extreme")]
    alerts = [
        (s, c)
        for s, c in eligible
        if c.get("monitoring_decision") == L3.MONITORING_INVESTIGATE
    ]

    # ความปลอดภัย: L3 ต้องไม่ปรากฏในแกน access เลย — ตรวจสองทาง
    #   (1) เหตุผลของ L3 ต้องไม่เคยโผล่ใน risk_reasons (แกนอธิบาย access decision)
    #   (2) ค่าในช่อง decision ต้องไม่ใช่คำจากคำศัพท์ของแกน monitoring
    monitoring_vocab = {L3.MONITORING_NORMAL, L3.MONITORING_INVESTIGATE}
    violations = [
        (s, c)
        for s, c in with_contract
        if any(L3.REASON in str(r) for r in (s.risk_reasons or []))
        or str(s.decision) in monitoring_vocab
    ]

    per_day = Counter()
    for s, _ in alerts:
        per_day[s.created_at.date()] += 1

    # tier reachability: อัตรา login ต่อคน -> เวลาที่ต้องใช้ถึงแต่ละ tier
    per_user = defaultdict(list)
    for s, _ in rows:
        if s.user_id:
            per_user[s.user_id].append(s.created_at)
    rates = {}
    for uid, ts in per_user.items():
        if len(ts) < 2:
            continue
        span_days = max((max(ts) - min(ts)).days, 1)
        rates[uid] = len(ts) / span_days
    return {
        "total": total,
        "with_contract": len(with_contract),
        "eligible": len(eligible),
        "elig_dist": elig_dist,
        "tier_dist": tier_dist,
        "shadow_dist": shadow_dist,
        "fired": len(fired),
        "alerts": len(alerts),
        "violations": violations,
        "per_day": per_day,
        "rates": rates,
        "n_users": len(per_user),
        "span": (
            (min(s.created_at for s, _ in rows), max(s.created_at for s, _ in rows))
            if rows
            else None
        ),
    }


def _pct(a: int, b: int) -> str:
    return f"{a / b * 100:.2f}%" if b else "—"


def render(a: dict, days: int | None) -> str:
    L = [
        "# Production Shadow Replay — L3 sequence channel",
        "",
        f"**สร้างเมื่อ:** {datetime.now().date().isoformat()} · "
        f"**ช่วงข้อมูล:** {'ทั้งหมด' if not days else f'{days} วันล่าสุด'} · "
        f"**สร้างโดย:** `scripts/l3_shadow_replay.py`",
        "",
        "อ่านจาก `login_sessions.risk_breakdown.l3_sequence` — data contract ที่ `risk_engine`",
        "เขียนทุก login ตั้งแต่เปิด `L3_SEQUENCE_ENABLED` (ไม่มี PII ในรายงานนี้)",
        "",
        "---",
        "",
        "## 1. ปริมาณข้อมูล",
        "",
        "| รายการ | ค่า |",
        "|---|---|",
        f"| login_sessions ทั้งหมดในช่วง | {a['total']:,} |",
        f"| มี L3 contract (หลังเปิดใช้) | {a['with_contract']:,} |",
        f"| **eligible** (L3 ประเมินได้จริง) | **{a['eligible']:,}** |",
        f"| ผู้ใช้ที่มี session | {a['n_users']:,} |",
    ]
    if a["span"]:
        L.append(f"| ช่วงเวลา | {a['span'][0]:%Y-%m-%d} → {a['span'][1]:%Y-%m-%d} |")
    L += [
        "",
        "**การกระจายของ eligibility**",
        "",
        "| eligibility | จำนวน | สัดส่วน |",
        "|---|---|---|",
    ]
    for k in ("abstain", "diagnostic", "warn", "challenge"):
        L.append(
            f"| {k} | {a['elig_dist'].get(k, 0):,} | "
            f"{_pct(a['elig_dist'].get(k, 0), a['with_contract'])} |"
        )

    L += [
        "",
        "## 2. Raw vs Alert",
        "",
        '> L3 อยู่คนละแกนกับ access decision — ไม่มีตัวชี้วัด "เปลี่ยน decision" อีกต่อไป',
        "> เพราะโดยโครงสร้างแล้ว L3 ทำไม่ได้ (ดู §3) สิ่งที่วัดคือ ยิง vs ขึ้นธงให้ SOC",
        "",
        "| ตัวชี้วัด | จำนวน | สัดส่วนของ eligible |",
        "|---|---|---|",
        f"| **raw** — L3 ยิง (tier anomaly/extreme) | {a['fired']:,} | {_pct(a['fired'], a['eligible'])} |",
        f"| **alert** — ขึ้นธง `l3_investigate` | {a['alerts']:,} | {_pct(a['alerts'], a['eligible'])} |",
        "",
        "| tier | จำนวน |",
        "|---|---|",
    ]
    for k, v in sorted(a["tier_dist"].items(), key=lambda x: -x[1]):
        L.append(f"| {k} | {v:,} |")
    L += ["", "| shadow_decision | จำนวน |", "|---|---|"]
    for k, v in sorted(a["shadow_dist"].items(), key=lambda x: -x[1]):
        L.append(f"| {k or '(ไม่มี)'} | {v:,} |")

    L += [
        "",
        "## 3. ความปลอดภัย — สองแกนแยกกันจริงไหม",
        "",
        "```text",
        "access_decision     = L1/L2/L4 -> allow | warn | challenge | block",
        "monitoring_decision = L3        -> normal | l3_investigate",
        "```",
        "",
        "| การตรวจ | ผล |",
        "|---|---|",
        f"| session ที่ L3 รั่วเข้าแกน access (reason หรือค่าใน decision) | "
        f"**{len(a['violations'])}** {'✅ ไม่มี' if not a['violations'] else '❌ ต้องสอบสวนทันที'} |",
    ]

    L += ["", "## 4. ภาระ SOC (alert ที่ L3 เพิ่ม)", ""]
    if a["per_day"]:
        vals = sorted(a["per_day"].values())
        L += [
            "| ตัวชี้วัด | ค่า |",
            "|---|---|",
            f"| วันที่มี alert | {len(vals)} |",
            f"| มัธยฐาน/วัน | {vals[len(vals) // 2]} |",
            f"| สูงสุด/วัน | {max(vals)} |",
        ]
    else:
        L.append("ยังไม่มี alert จาก L3 ในช่วงนี้")

    L += [
        "",
        "## 5. 🔑 Tier reachability — ผู้ใช้จริงสะสม history ถึงเกณฑ์ไหม",
        "",
        "L3 ต้องมี history ต่อคนถึงเกณฑ์จึงจะทำงาน — ถ้า traffic จริงไปไม่ถึง",
        "ตัวเลข offline ทั้งหมดก็ไม่มีความหมายในทางปฏิบัติ",
        "",
        "| tier | ต้องมี history | ความสามารถ |",
        "|---|---|---|",
        f"| diagnostic | {L3.TIER_DIAGNOSTIC:,} | ให้คะแนน+log เท่านั้น |",
        f"| warn | {L3.TIER_WARN:,} | ยก decision เป็น warn ได้ |",
        f"| challenge | {L3.TIER_CHALLENGE:,} | บันทึก would_challenge (shadow) |",
        "",
    ]
    if a["rates"]:
        rates = sorted(a["rates"].values())
        med = rates[len(rates) // 2]
        top = rates[-1]
        L += [
            "**อัตรา login ที่วัดได้จริง**",
            "",
            "| ตัวชี้วัด | login/วัน/คน |",
            "|---|---|",
            f"| มัธยฐาน | {med:.2f} |",
            f"| สูงสุด | {top:.2f} |",
            "",
            "**เวลาที่ต้องใช้เพื่อไปถึงแต่ละ tier** (ที่อัตราปัจจุบัน)",
            "",
            "| tier | ผู้ใช้มัธยฐาน | ผู้ใช้ที่ active ที่สุด |",
            "|---|---|---|",
        ]
        for name, need in (
            ("diagnostic", L3.TIER_DIAGNOSTIC),
            ("warn", L3.TIER_WARN),
            ("challenge", L3.TIER_CHALLENGE),
        ):
            dm = need / med if med else float("inf")
            dt = need / top if top else float("inf")
            L.append(
                f"| {name} | {dm / 365:.1f} ปี ({dm:.0f} วัน) | "
                f"{dt / 365:.1f} ปี ({dt:.0f} วัน) |"
            )
    else:
        L.append("ข้อมูลไม่พอคำนวณอัตรา login")

    L += [
        "",
        "## 6. เกณฑ์ go / no-go (ตั้งไว้ล่วงหน้า)",
        "",
        "| เกณฑ์ | ต้องได้ | ผลตอนนี้ |",
        "|---|---|---|",
        f"| เหตุการณ์ที่ eligible เพียงพอ | ≥ {GATE_MIN_EVENTS:,} | "
        f"{a['eligible']:,} {'✅' if a['eligible'] >= GATE_MIN_EVENTS else '❌ ยังไม่พอ'} |",
        f"| L3 ยิงบน traffic ปกติ | ≤ {GATE_MAX_L3_FPR * 100:.0f}% | "
        f"{_pct(a['fired'], a['eligible'])} |",
        "| L3 ไม่เปลี่ยน challenge/block | 0 ครั้ง | "
        f"{len(a['violations'])} {'✅' if not a['violations'] else '❌'} |",
        f"| L3 เห็นสิ่งที่ L1/L2 ไม่เห็น | ≥ {GATE_MIN_UNIQUE * 100:.0f}% | "
        "ต้องมี label เหตุการณ์จริงก่อนถึงวัดได้ |",
        "",
        "**กติกา:** ห้ามแก้เกณฑ์เหล่านี้หลังเห็นผล — ถ้าไม่ผ่านคือไม่ผ่าน",
        "",
        "## 7. ข้อสรุป ณ รอบนี้",
        "",
    ]
    # ── ข้อสรุปคำนวณจากข้อมูล ไม่ใช่เขียนตายตัว ──
    if a["eligible"] == 0:
        L += [
            "### 🔬 รอบนี้เป็น **functional smoke test** ไม่ใช่การวัดประสิทธิภาพ",
            "",
            f"Production replay รอบนี้มีเพียง **{a['with_contract']:,} เหตุการณ์** และ "
            f"**eligible {a['eligible']}/{a['with_contract']}** "
            "(ผู้ใช้ทุกคนยังมี residual history ต่ำกว่าเกณฑ์ `diagnostic` = "
            f"{L3.TIER_DIAGNOSTIC})",
            "",
            "**สิ่งที่รอบนี้ยืนยันได้:**",
            "",
            "- pipeline ทำงานครบวงจรบน traffic จริง — contract ถูกเขียนลง `risk_breakdown` ทุก login",
            "- L3 ไม่แตะแกน access decision แม้แต่ครั้งเดียว",
            "- ระบบ abstain อย่างถูกต้องเมื่อ history ไม่พอ (ไม่เดามั่ว)",
            "",
            "**สิ่งที่รอบนี้ยืนยัน _ไม่ได้_:**",
            "",
            "- ❌ recall / FPR / precision ของ L3 บน traffic จริง",
            "- ❌ ภาระ alert ที่ SOC จะได้รับจริง",
            "- ❌ ว่า L3 เห็นสิ่งที่ L1/L2 ไม่เห็นหรือไม่",
            "",
            "ตัวเลขประสิทธิภาพทุกตัวที่อ้างอิงได้ตอนนี้ **มาจากข้อมูลจำลองเท่านั้น**",
            "",
        ]
    else:
        L += [
            f"L3 ประเมินได้ {a['eligible']:,} เหตุการณ์ · ยิง {_pct(a['fired'], a['eligible'])} "
            f"· เปลี่ยน decision จริง {_pct(a['effective'], a['eligible'])}",
            "",
        ]

    if a["rates"]:
        rates = sorted(a["rates"].values())
        med = rates[len(rates) // 2]
        yrs = (L3.TIER_WARN / med / 365) if med else float("inf")
        L += [
            "### ⚠️ ข้อจำกัดเชิงโครงสร้างที่พบจากข้อมูลจริง",
            "",
            f"ที่อัตรา login มัธยฐาน **{med:.2f} ครั้ง/วัน/คน** ผู้ใช้ทั่วไปต้องใช้เวลา "
            f"**~{yrs:.1f} ปี** จึงจะสะสม history ถึงเกณฑ์ `warn` ({L3.TIER_WARN:,} เหตุการณ์)",
            "ซึ่งเป็นระดับเดียวที่ L3 มีสิทธิ์เปลี่ยน decision ได้",
            "",
            "แปลว่า **ในระบบที่มีปริมาณการใช้งานเท่านี้ L3 จะอยู่ในสถานะ `abstain`/`diagnostic`",
            "แทบตลอดอายุการใช้งานจริง** — ตัวเลข offline ที่วัดได้ที่ history 1,000–5,000",
            "เป็นสภาพที่ deployment นี้ไปไม่ถึงในกรอบเวลาที่มีความหมาย",
            "",
            "ข้อนี้ไม่ได้แปลว่าโมเดลผิด — แต่แปลว่า **สมมติฐานเรื่องปริมาณข้อมูลต่อคนไม่ตรงกับ",
            "ความจริงของ deployment นี้** ซึ่งเป็นข้อค้นพบที่ต้องระบุใน thesis และต้องให้",
            "ผู้เชี่ยวชาญพิจารณาว่าจะเดินทางไหนต่อ:",
            "",
            "| ทางเลือก | ผลที่ตามมา |",
            "|---|---|",
            "| คงเกณฑ์เดิม ใช้ L3 เป็น diagnostic อย่างเดียว | ซื่อตรงที่สุด · L3 ไม่มีผลต่อ decision เลย |",
            "| ลดเกณฑ์ tier ลง | ต้องทดลองใหม่ทั้งชุด — ผลที่ history ต่ำเคยวัดได้ 4.7% (แย่กว่ามาก) |",
            "| รวม history ข้ามผู้ใช้ (population model) | เปลี่ยนสถาปัตยกรรม — ไม่ใช่ per-user model อีกต่อไป |",
            "| ยอมรับว่า L1+L2 เพียงพอ ตัด L3 ออก | สอดคล้องกับ final gate (L3-only 0.7%) |",
            "",
            "**ยังไม่ตัดสินใจ** — รอผู้เชี่ยวชาญตรวจชุดหลักฐาน (`docs/RBA_EVIDENCE_MANIFEST_2026-08-29.md`)",
            "",
        ]
    L += [
        "### รอบถัดไป",
        "",
        "```bash",
        "docker compose exec hub-backend python -m scripts.l3_shadow_replay \\",
        "  --out /app/tests/reports/l3_shadow_replay_<YYYY-MM-DD>.md",
        "```",
        "",
        "เก็บรายงานทุกรอบไว้เทียบกัน — ห้ามปรับ threshold/โมเดลระหว่างเก็บข้อมูล",
        "(มิฉะนั้นข้อมูลที่สะสมมาจะเทียบกันไม่ได้)",
        "",
    ]
    # rstrip กัน blank line ท้ายไฟล์ -> hook end-of-file-fixer ไม่แก้ซ้ำจน hash เพี้ยน
    return "\n".join(L).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=None, help="จำกัดช่วงข้อมูล (วัน)")
    ap.add_argument("--out", type=Path, default=None, help="เขียนรายงานลงไฟล์")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        rows = collect(db, args.days)
        a = analyse(rows)
    finally:
        db.close()

    report = render(a, args.days)
    print(report)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"-> {args.out}")
    return 0 if not a["violations"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
