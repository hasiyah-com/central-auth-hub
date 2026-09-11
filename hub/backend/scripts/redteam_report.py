"""Red-team report — เก็บผลการโจมตีจริง แล้วเทียบกับ simulated attack.

═══════════════════════════════════════════════════════════════════════════
ทำไมต้องมี
═══════════════════════════════════════════════════════════════════════════
recall ที่วัดได้ตอนนี้มาจาก **simulated attack** (attacker modeling) ทั้งหมด
→ จุดอ่อนเชิง methodology: "แล้วรู้ได้ไงว่า attack ที่จำลองสมจริง?"

สคริปต์นี้ปิดช่องนั้น: ให้ผู้วิจัยโจมตีระบบ**จริง** (VPN/เครื่องอื่น/เวลาผิด) แล้ว
mark session เหล่านั้นเป็น red-team → เทียบ **คะแนนจริง vs คะแนนจำลอง** ของ
attacker model ระดับเดียวกัน

ถ้าคะแนนใกล้กัน → **พิสูจน์ว่า simulated attack เชื่อถือได้** (external validity)

═══════════════════════════════════════════════════════════════════════════
วิธีใช้ (3 ขั้น)
═══════════════════════════════════════════════════════════════════════════
1. **ทำ red-team จริง** ตาม docs/guides/RED_TEAM_GUIDE.md
   (เปิด VPN ต่างประเทศ / ใช้มือถือ / login ตี 3 ฯลฯ)

2. **mark session** ที่เพิ่งทำ (ดู session ล่าสุดของ user ตัวเอง):
   python -m scripts.redteam_report list --email you@gmail.com
   python -m scripts.redteam_report mark <session_id> --model vpn --note "NordVPN Japan"

3. **ดูรายงานเทียบ simulated**:
   python -m scripts.redteam_report report

═══════════════════════════════════════════════════════════════════════════
วิธีเก็บ label (ไม่แตะ schema)
═══════════════════════════════════════════════════════════════════════════
ใช้ `MLFeedback` ที่มีอยู่แล้ว — `label = "true_positive"` (= attack จริง) และเก็บ
attacker model ใน `note` เป็น `redteam:<model>|<free text>` → ไม่ต้อง migration
และ `export_labeled_data.py` จะดึงไปเป็น training label ให้อัตโนมัติ
"""

import argparse
import statistics
import sys
from collections import defaultdict

from app.database import SessionLocal
from app.models import LoginSession, MLFeedback, User

REDTEAM_PREFIX = "redteam:"
VALID_MODELS = ("very_naive", "naive", "vpn", "targeted")

# คะแนน mean ของ simulated attack แต่ละระดับ (จาก attack_set_eval_2026-07-22.md)
# ใช้เป็น baseline เทียบ — อัปเดตถ้ารัน evaluate_attack_set ใหม่
SIMULATED_BASELINE = {
    "very_naive": {"mean_score": 1.000, "recall": 100.0},
    "naive": {"mean_score": 1.000, "recall": 100.0},
    "vpn": {"mean_score": 0.932, "recall": 100.0},
    "targeted": {"mean_score": 0.298, "recall": 8.7},
}

DETECTED = {"block", "challenge", "would_block", "would_challenge", "mfa", "would_mfa"}


def _redteam_rows(db):
    """คืน [(session, model, note)] ของ session ที่ mark เป็น red-team แล้ว."""
    out = []
    fbs = db.query(MLFeedback).filter(MLFeedback.note.isnot(None)).all()
    for fb in fbs:
        if not (fb.note or "").startswith(REDTEAM_PREFIX):
            continue
        body = fb.note[len(REDTEAM_PREFIX) :]
        model, _, free = body.partition("|")
        s = db.query(LoginSession).filter(LoginSession.id == fb.session_id).first()
        if s:
            out.append((s, model.strip(), free.strip()))
    return out


def cmd_list(args) -> int:
    """แสดง session ล่าสุด (ไว้หา id ที่จะ mark)."""
    db = SessionLocal()
    try:
        q = db.query(LoginSession).order_by(LoginSession.created_at.desc())
        if args.email:
            u = db.query(User).filter(User.email == args.email).first()
            if not u:
                print(f"ไม่พบ user {args.email}")
                return 1
            q = q.filter(LoginSession.user_id == u.id)
        rows = q.limit(args.limit).all()
        if not rows:
            print("ไม่มี session")
            return 0
        print(
            f"{'session_id':<38}{'เวลา (UTC)':<18}{'ประเทศ':<8}{'score':>7}  {'decision':<14}อุปกรณ์"
        )
        print("-" * 110)
        for s in rows:
            print(
                f"{str(s.id):<38}{s.created_at:%Y-%m-%d %H:%M}   "
                f"{(s.geo_country or '-'):<8}{float(s.risk_score or 0):>7.3f}  "
                f"{(s.decision or '-'):<14}{s.browser or '-'}/{s.device_type or '-'}"
            )
        print("\nmark ด้วย:")
        print(
            "  python -m scripts.redteam_report mark <session_id> --model vpn --note 'NordVPN Japan'"
        )
        return 0
    finally:
        db.close()


def cmd_mark(args) -> int:
    """mark session เป็น red-team attack (label ผ่าน MLFeedback ที่มีอยู่)."""
    if args.model not in VALID_MODELS:
        print(f"--model ต้องเป็นหนึ่งใน {VALID_MODELS}")
        return 1
    db = SessionLocal()
    try:
        s = db.query(LoginSession).filter(LoginSession.id == args.session_id).first()
        if not s:
            print(f"ไม่พบ session {args.session_id}")
            return 1
        note = f"{REDTEAM_PREFIX}{args.model}|{args.note or ''}"
        fb = db.query(MLFeedback).filter(MLFeedback.session_id == s.id).first()
        if fb:
            fb.label = "true_positive"
            fb.note = note
            action = "อัปเดต"
        else:
            # marked_by = nullable=False → ใช้ admin คนแรก (ผู้วิจัยที่ทำ red-team)
            marker = (
                db.query(User).filter(User.is_hub_admin.is_(True)).first()
                or db.query(User).first()
            )
            if not marker:
                print("ไม่พบ user สำหรับ marked_by")
                return 1
            db.add(
                MLFeedback(
                    session_id=s.id,
                    label="true_positive",
                    note=note,
                    marked_by=marker.id,
                )
            )
            action = "เพิ่ม"
        # ground truth flag — ให้ export_labeled_data / evaluate ดึงไปใช้ได้
        s.is_account_takeover = True
        db.commit()
        print(f"{action} red-team label")
        print(f"   session : {s.id}")
        print(f"   model   : {args.model}")
        print(f"   score   : {float(s.risk_score or 0):.3f}   decision: {s.decision}")
        print(f"   note    : {args.note or '-'}")
        return 0
    finally:
        db.close()


def cmd_unmark(args) -> int:
    db = SessionLocal()
    try:
        fb = (
            db.query(MLFeedback)
            .filter(MLFeedback.session_id == args.session_id)
            .first()
        )
        s = db.query(LoginSession).filter(LoginSession.id == args.session_id).first()
        if fb:
            db.delete(fb)
        if s:
            s.is_account_takeover = False
        db.commit()
        print(f"ลบ red-team label ของ {args.session_id}")
        return 0
    finally:
        db.close()


def cmd_report(args) -> int:
    """รายงานเทียบ red-team จริง vs simulated."""
    db = SessionLocal()
    try:
        rows = _redteam_rows(db)
        if not rows:
            print(" ยังไม่มี session ที่ mark เป็น red-team")
            print("   ทำตาม docs/guides/RED_TEAM_GUIDE.md แล้ว mark ด้วย:")
            print(
                "   python -m scripts.redteam_report mark <session_id> --model <model>"
            )
            return 0

        by_model = defaultdict(list)
        for s, model, note in rows:
            by_model[model].append((s, note))

        print("=" * 78)
        print("Red-Team Validation — attack จริง vs simulated")
        print("=" * 78)

        # ── รายละเอียดแต่ละเคส ──
        print(f"\n--- เคสที่ทำจริง ({len(rows)} sessions) ---")
        print(
            f"{'model':<12}{'เวลา':<18}{'ประเทศ':<8}{'score':>7}  {'decision':<14}note"
        )
        print("-" * 90)
        for s, model, note in sorted(rows, key=lambda r: r[0].created_at):
            print(
                f"{model:<12}{s.created_at:%Y-%m-%d %H:%M}   "
                f"{(s.geo_country or '-'):<8}{float(s.risk_score or 0):>7.3f}  "
                f"{(s.decision or '-'):<14}{note[:30]}"
            )

        # ── เทียบกับ simulated ──
        print("\n--- เทียบกับ simulated (attacker modeling) ---")
        print(
            f"{'model':<12}{'n':>3}{'real score':>12}{'sim score':>11}{'diff':>8}"
            f"{'real recall':>13}{'sim recall':>12}"
        )
        print("-" * 78)
        verdicts = []
        for model in VALID_MODELS:
            items = by_model.get(model)
            if not items:
                continue
            scores = [float(s.risk_score or 0) for s, _ in items]
            real_mean = statistics.mean(scores)
            det = sum(1 for s, _ in items if (s.decision or "") in DETECTED)
            real_recall = det / len(items) * 100
            base = SIMULATED_BASELINE.get(model, {})
            sim_mean = base.get("mean_score", 0.0)
            sim_recall = base.get("recall", 0.0)
            diff = real_mean - sim_mean
            verdicts.append((model, abs(diff)))
            print(
                f"{model:<12}{len(items):>3}{real_mean:>12.3f}{sim_mean:>11.3f}"
                f"{diff:>+8.3f}{real_recall:>12.1f}%{sim_recall:>11.1f}%"
            )

        # ── สรุปความน่าเชื่อถือ ──
        print("\n--- สรุป: simulated attack สมจริงแค่ไหน ---")
        if verdicts:
            worst = max(d for _, d in verdicts)
            mean_gap = statistics.mean(d for _, d in verdicts)
            print(f"  ค่าต่างเฉลี่ย |real − sim| = {mean_gap:.3f}  (มากสุด {worst:.3f})")
            if worst <= 0.15:
                print("  คะแนนจริงใกล้เคียง simulated มาก → attacker modeling น่าเชื่อถือ")
            elif worst <= 0.30:
                print("  ใกล้เคียงพอสมควร — ระบุ gap ในเล่มเป็นข้อจำกัด")
            else:
                print("  ต่างมาก — ควรทบทวนพารามิเตอร์ใน build_attack_set.py")
        n_missing = [m for m in VALID_MODELS if m not in by_model]
        if n_missing:
            print(f"  ยังไม่ได้ทดสอบจริง: {', '.join(n_missing)}")
        print("\nred-team = ground truth จริง (n น้อยแต่ label ถูก 100%)")
        print("   ใช้ยืนยันความสมจริงของ simulated attack ที่ใช้วัด recall หลัก")
        print("=" * 78)
        return 0
    finally:
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="ดู session ล่าสุด (หา id)")
    p_list.add_argument("--email", help="กรองเฉพาะ user นี้")
    p_list.add_argument("--limit", type=int, default=15)
    p_list.set_defaults(func=cmd_list)

    p_mark = sub.add_parser("mark", help="mark session เป็น red-team attack")
    p_mark.add_argument("session_id")
    p_mark.add_argument(
        "--model", required=True, help=f"attacker model: {', '.join(VALID_MODELS)}"
    )
    p_mark.add_argument("--note", help="รายละเอียด เช่น 'NordVPN Japan, มือถือ'")
    p_mark.set_defaults(func=cmd_mark)

    p_un = sub.add_parser("unmark", help="ยกเลิก label")
    p_un.add_argument("session_id")
    p_un.set_defaults(func=cmd_unmark)

    p_rep = sub.add_parser("report", help="รายงานเทียบ real vs simulated")
    p_rep.set_defaults(func=cmd_report)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
