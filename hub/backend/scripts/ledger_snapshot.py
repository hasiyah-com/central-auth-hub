"""snapshot ของ holdout ledger สำหรับเก็บใน git + ตรวจว่าตรงกับ ledger จริง.

ledger ตัวจริง (`ml-service/data/hybrid_experiment/holdout_ledger.json`) อยู่ในโฟลเดอร์
ที่ gitignore เพราะอยู่รวมกับข้อมูลทดลอง · ผู้ตรวจจาก git จึงไม่เห็นว่า seed ไหนถูกเปิด
กี่ครั้ง (B68) · snapshot คัดเฉพาะฟิลด์ที่ตรวจย้อนได้ และตัดค่าที่เป็น path ส่วนตัวทิ้ง

    cd hub/backend
    python -m scripts.ledger_snapshot build   # เขียน tests/provenance/holdout_ledger_snapshot.json
    python -m scripts.ledger_snapshot check   # ตรวจก่อนสร้าง release tag · ไม่ตรง = exit 1

ต้องรันบน host (ledger ไม่ได้ mount ในคอนเทนเนอร์)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parents[1] if len(BACKEND.parents) > 1 else BACKEND
DEFAULT_LEDGER = (
    REPO / "ml-service" / "data" / "hybrid_experiment" / "holdout_ledger.json"
)
DEFAULT_SNAPSHOT = BACKEND / "tests" / "provenance" / "holdout_ledger_snapshot.json"
FREEZE_RECORD = BACKEND / "tests" / "scoring_freeze.json"

# ฟิลด์ที่เก็บ — อย่างอื่นไม่เข้า snapshot
KEPT = (
    "seeds",
    "purpose",
    "open_count",
    "first_opened_at",
    "last_opened_at",
    "frozen_commit",
    "reopened",
    "population",
    "note",
    "correction",
    "history",
    "artifact_sha256",
    "invalidated_runs",
)
# ฟิลด์ที่ต้องตรงกันระหว่าง snapshot กับ ledger
COMPARED = KEPT

_PRIVATE_PATH = re.compile(r"([A-Za-z]:\\|\\\\|/Users/|/home/|AppData)")


def _looks_private(value) -> bool:
    return isinstance(value, str) and bool(_PRIVATE_PATH.search(value))


def _entry(raw: dict) -> tuple[dict, int]:
    out, removed = {}, 0
    for key in KEPT:
        if key not in raw:
            continue
        if _looks_private(raw[key]):
            removed += 1
            continue
        out[key] = raw[key]
    removed += sum(1 for k, v in raw.items() if k not in KEPT and _looks_private(v))
    # ledger ของ final gate รุ่นแรกไม่มี purpose — ระบุให้ชัดแทนการปล่อยว่าง
    out.setdefault("purpose", "final_gate")
    return out, removed


def scoring_fingerprint(files: dict) -> str:
    blob = json.dumps(files, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def build_snapshot(ledger: dict, *, scoring_files: dict, commit: str) -> dict:
    entries, removed = {}, 0
    for key in sorted(ledger):
        entry, n = _entry(ledger[key])
        entries[key] = entry
        removed += n
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": commit,
        "scoring_fingerprint": scoring_fingerprint(scoring_files),
        "source": "ml-service/data/hybrid_experiment/holdout_ledger.json (gitignored)",
        "sanitized_fields": removed,
        "entries": entries,
    }


def compare(snapshot: dict, ledger: dict) -> list[str]:
    """รายการความต่าง · ว่าง = ตรงกัน (ไม่เทียบ generated_at/commit/fingerprint)."""
    problems = []
    snap_entries = snapshot.get("entries") or {}
    for key in sorted(set(ledger) - set(snap_entries)):
        problems.append(f"{key}: มีใน ledger แต่ไม่มีใน snapshot")
    for key in sorted(set(snap_entries) - set(ledger)):
        problems.append(f"{key}: มีใน snapshot แต่ไม่มีใน ledger")
    for key in sorted(set(ledger) & set(snap_entries)):
        expected, _ = _entry(ledger[key])
        got = snap_entries[key]
        for field in COMPARED:
            if expected.get(field) != got.get(field):
                problems.append(
                    f"{key}: {field} ไม่ตรง (ledger {expected.get(field)!r} "
                    f"snapshot {got.get(field)!r})"
                )
    return problems


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception as e:  # noqa: BLE001
        return f"unavailable: {e}"


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.write_bytes(text.encode("utf-8"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("build", "check"))
    ap.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    ap.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    a = ap.parse_args(argv)

    if not a.ledger.exists():
        print(f"ไม่พบ ledger ที่ {a.ledger} — ต้องรันบน host", file=sys.stderr)
        return 2
    ledger = json.loads(a.ledger.read_text(encoding="utf-8"))

    if a.command == "build":
        files = json.loads(FREEZE_RECORD.read_text(encoding="utf-8"))["files"]
        snap = build_snapshot(ledger, scoring_files=files, commit=_git_commit())
        _write(a.snapshot, snap)
        print(
            f"เขียน {a.snapshot} ({len(snap['entries'])} รายการ · "
            f"ตัด path ส่วนตัว {snap['sanitized_fields']} ฟิลด์)"
        )
        return 0

    if not a.snapshot.exists():
        print(f"ไม่พบ snapshot ที่ {a.snapshot}", file=sys.stderr)
        return 1
    problems = compare(json.loads(a.snapshot.read_text(encoding="utf-8")), ledger)
    if problems:
        print("snapshot ไม่ตรงกับ ledger:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("snapshot ตรงกับ ledger")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
