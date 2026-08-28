"""ทดสอบโมเดล V7 (sequence, shadow bundle) บนชุดข้อมูล V2 ที่มันไม่เคยเห็น.

ทำไมถึงมีค่า:
  V7 เทรนบน synthetic ของตัวเอง (5,000 sequence, seed 42, normal_staggered)
  แล้วรายงาน recall 90.9% / PR-AUC 0.989 บนข้อมูลชุดเดียวกัน
  -> ยังไม่รู้ว่า generalize ไหม; release_gate.json เองก็เขียนว่าต้อง replay ข้อมูลอื่นก่อน enforce

  ชุด V2 สร้างจาก generator คนละตัว (anchor พฤติกรรมผู้ใช้จริง 12 คน, campus NAT, ไม่มี geo)
  -> เป็น held-out จริง ไม่ใช่ test split ของตัวเอง

การแมปฟิลด์ (V2 -> 8 ฟิลด์ที่ V7 ต้องการ):
  timestamp           <- created_at
  session_duration    <- duration_min
  concurrent_sessions <- concurrent_session_count
  scope_sensitivity   <- ตาม subsystem (HUB 0.0 / SUB_A 0.8 / SUB_B 0.6) เหมือน features_v2
  subsystem           <- subsystem
  browser_version     <- เลข major version จาก browser / user_agent
  failed_1h           <- นับ login ที่ล้มเหลวใน 60 นาทีก่อนหน้า (จาก stream ของ user)
  success_10m         <- นับ login สำเร็จใน 10 นาทีก่อนหน้า

โปรโตคอล: ใช้ split เดียวกับ run_4layer_v2.py (normal 20% ท้าย = test, attack ทั้ง 240 = test)
เพื่อเทียบตัวเลขกันได้ตรงๆ

Run:
    py ml-service/scripts/eval_v7_on_v2.py --bundle <path>/sequence_model_v7.joblib
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
TS = "%Y-%m-%d %H:%M:%S"
SCOPE = {"HUB": 0.0, "SUB_A": 0.8, "SUB_B": 0.6}
WINDOW = 4

EXPECTED = (
    "combined_ato",
    "concurrent_sessions",
    "failed_spike",
    "login_velocity",
    "new_device",
    "new_os",
    "new_passkey",
    "new_ua_family",
    "off_hours",
    "permission_change",
    "subsystem_lateral",
)


def parse(s: str) -> datetime:
    return datetime.strptime(s, TS)


def browser_version(row: dict) -> float:
    """เลข major version — ต้องเป็นตัวเลขเพราะ V7 คำนวณ slope ของมัน."""
    m = re.search(r"(\d+)", row.get("browser", ""))
    if m:
        return float(m.group(1))
    m = re.search(
        r"FBAV/(\d+)", row.get("user_agent", "")
    )  # in-app browser ของ Facebook
    return float(m.group(1)) if m else 0.0


def to_event(row: dict, stream: list[dict]) -> dict:
    """แปลง 1 แถวของ V2 -> event ตาม contract ของ V7."""
    now = parse(row["created_at"])
    prev = [r for r in stream if parse(r["created_at"]) < now]
    failed_1h = sum(
        1
        for r in prev
        if r["login_successful"] == "False"
        and parse(r["created_at"]) >= now - timedelta(hours=1)
    )
    success_10m = sum(
        1
        for r in prev
        if r["login_successful"] == "True"
        and parse(r["created_at"]) >= now - timedelta(minutes=10)
    )
    return {
        "timestamp": now.isoformat(),
        "failed_1h": failed_1h,
        "success_10m": success_10m,
        "concurrent_sessions": int(float(row.get("concurrent_session_count", 0) or 0)),
        "session_duration": float(row.get("duration_min", 0) or 0),
        "scope_sensitivity": SCOPE.get(row["subsystem"], 0.1),
        "browser_version": browser_version(row),
        "subsystem": row["subsystem"],
    }


def build_windows() -> tuple[list[dict], list[dict]]:
    """คืน (normal test windows, attack windows) — แต่ละอันมี 4 events เรียงเวลา."""
    logins = list(csv.DictReader(open(DATA / "logins_v2.csv", encoding="utf-8")))
    attacks = list(csv.DictReader(open(DATA / "attacks_v2.csv", encoding="utf-8")))

    by_key: dict[tuple, list[dict]] = defaultdict(list)
    for r in logins:
        by_key[(r["alias"], r["normal_condition"])].append(r)
    for rows in by_key.values():
        rows.sort(key=lambda r: r["created_at"])

    # ── normal: 20% ท้ายของแต่ละคน (split เดียวกับ run_4layer_v2) ──
    normal_windows: list[dict] = []
    for (alias, cond), rows in by_key.items():
        if cond != "staggered":
            continue
        k = int(len(rows) * 0.8)
        for i in range(max(k, WINDOW - 1), len(rows)):
            win = rows[i - WINDOW + 1 : i + 1]
            normal_windows.append(
                {
                    "alias": alias,
                    "scenario": "normal",
                    "label": 0,
                    "events": [to_event(r, rows[: i + 1]) for r in win],
                }
            )

    # ── attack: frozen — history = normal(staggered) ก่อนหน้า + context ของ scenario เดียวกัน ──
    atk_by_user: dict[str, list[dict]] = defaultdict(list)
    for r in attacks:
        atk_by_user[r["alias"]].append(r)

    attack_windows: list[dict] = []
    for alias, rows in atk_by_user.items():
        rows.sort(key=lambda r: r["created_at"])
        base = by_key[(alias, "staggered")]
        for r in rows:
            if r["row_kind"] != "attack":
                continue
            t = r["created_at"]
            ctx = [
                x
                for x in rows
                if x["row_kind"] == "context"
                and x["scenario"] == r["scenario"]
                and x["created_at"] < t
            ]
            hist = sorted(
                [x for x in base if x["created_at"] < t] + ctx,
                key=lambda x: x["created_at"],
            )
            if len(hist) < WINDOW - 1:
                continue
            win_rows = hist[-(WINDOW - 1) :] + [r]
            stream = hist + [r]
            attack_windows.append(
                {
                    "alias": alias,
                    "scenario": r["scenario"],
                    "label": 1,
                    "events": [to_event(x, stream) for x in win_rows],
                }
            )
    return normal_windows, attack_windows


def verify_bundle(path: Path) -> None:
    """ตรวจ integrity ก่อนโหลด — manifest มี sha256 ไว้อยู่แล้ว แต่ไม่มีใครเช็ก.

    ถ้าไม่เช็ก joblib จะพังเป็น zlib error ที่อ่านไม่รู้เรื่อง แทนที่จะบอกว่าไฟล์เสีย
    """
    import hashlib

    manifest = path.with_name("model_manifest_v7.json")
    if not manifest.exists():
        print(f"เตือน: ไม่พบ {manifest.name} — ข้ามการตรวจ integrity")
        return
    want = (
        json.loads(manifest.read_text(encoding="utf-8")).get("files", {}).get(path.name)
    )
    got = hashlib.sha256(path.read_bytes()).hexdigest()
    if want and got != want:
        msg = [
            "artifact ไม่ตรง manifest — ไฟล์เสียหรือไม่ใช่ตัวที่ปล่อยออกมา",
            f"   ไฟล์   : {path}",
            f"   ขนาด   : {path.stat().st_size:,} bytes",
            f"   sha256 : {got}",
            f"   ต้องการ: {want}",
            "   -> ขอไฟล์ใหม่จากเครื่องที่เทรน (อย่ารันต่อ ผลลัพธ์เชื่อไม่ได้)",
        ]
        raise SystemExit(chr(10).join(msg))
    print(f"integrity ผ่าน — sha256 ตรง manifest ({got[:16]}...)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True, type=Path)
    ap.add_argument(
        "--runtime", type=Path, help="โฟลเดอร์ที่มี shadow_sequence_runtime_v7.py"
    )
    args = ap.parse_args()

    rt_dir = args.runtime or args.bundle.parents[2] / "scripts"
    sys.path.insert(0, str(rt_dir))
    try:
        from shadow_sequence_runtime_v7 import ShadowSequenceRuntime
    except ImportError as exc:
        raise SystemExit(f"หา shadow_sequence_runtime_v7.py ไม่เจอที่ {rt_dir}: {exc}")

    verify_bundle(args.bundle)
    try:
        rt = ShadowSequenceRuntime(args.bundle)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            chr(10).join(
                [
                    f"โหลด bundle ไม่ได้: {type(exc).__name__}: {exc}",
                    "ถ้าเป็น zlib error แปลว่าไฟล์เสีย -> ขอ artifact ใหม่จากเครื่องที่เทรน",
                ]
            )
        )
    print(f"โหลด V7 แล้ว — version {rt.version} · threshold {rt.threshold:.4f}")

    normal, attack = build_windows()
    print(f"หน้าต่างที่สร้างได้: normal(test) {len(normal)} · attack {len(attack)}\n")

    rows = []
    for w in normal + attack:
        p = rt.score(w["events"])
        rows.append({**w, "prob": p, "flag": int(p >= rt.threshold)})

    n = [r for r in rows if r["label"] == 0]
    a = [r for r in rows if r["label"] == 1]
    tp = sum(r["flag"] for r in a)
    fp = sum(r["flag"] for r in n)
    recall = tp / len(a) if a else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    f1 = 2 * prec * recall / (prec + recall) if (prec + recall) else 0.0

    try:
        from sklearn.metrics import average_precision_score, roc_auc_score

        y = [r["label"] for r in rows]
        s = [r["prob"] for r in rows]
        roc, pr = roc_auc_score(y, s), average_precision_score(y, s)
    except Exception:  # noqa: BLE001
        roc = pr = float("nan")

    print("=" * 66)
    print("V7 sequence model บนชุด V2 (ไม่เคยเห็นมาก่อน)")
    print(f"  Recall {recall:.1%} | Precision {prec:.1%} | F1 {f1:.3f}")
    print(
        f"  FPR {fp / len(n):.2%} ({fp}/{len(n)}) | ROC-AUC {roc:.3f} | PR-AUC {pr:.3f}"
    )

    print("\nแยกตามชนิด attack")
    print(f"  {'scenario':22}{'n':>4}{'detect':>9}{'mean prob':>12}")
    per_sc = {}
    for sc in EXPECTED:
        g = [r for r in a if r["scenario"] == sc]
        if not g:
            continue
        d = sum(r["flag"] for r in g) / len(g)
        mp = sum(r["prob"] for r in g) / len(g)
        per_sc[sc] = {"n": len(g), "detect": d, "mean_prob": mp}
        print(f"  {sc:22}{len(g):>4}{d:>8.1%}{mp:>12.3f}")

    print("\nการกระจายของ probability บน normal test")
    buckets = Counter()
    for r in n:
        buckets[min(int(r["prob"] * 10), 9)] += 1
    for b in sorted(buckets):
        print(f"  {b / 10:.1f}-{(b + 1) / 10:.1f}  {buckets[b]:4}")

    out = {
        "bundle": str(args.bundle),
        "threshold": rt.threshold,
        "n_normal_test": len(n),
        "n_attack": len(a),
        "recall": recall,
        "precision": prec,
        "f1": f1,
        "fpr": fp / len(n) if n else 0.0,
        "roc_auc": roc,
        "pr_auc": pr,
        "per_scenario": per_sc,
    }
    (DATA / "v7_on_v2_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nบันทึก -> {DATA / 'v7_on_v2_results.json'}")


if __name__ == "__main__":
    main()
