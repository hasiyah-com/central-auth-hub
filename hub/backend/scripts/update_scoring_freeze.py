"""สร้าง/อัปเดตบันทึก freeze ของ scoring logic.

การอัปเดตต้องเป็นการตัดสินใจที่ **ตั้งใจ** เสมอ — สคริปต์นี้บังคับให้ใส่เหตุผล

    python -m scripts.update_scoring_freeze --reason "..." --unfreeze-when "..."
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from tests.test_scoring_freeze import RECORD, current_fingerprint  # noqa: E402


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=BACKEND, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception as e:  # noqa: BLE001
        return f"unavailable: {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reason", required=True, help="ทำไมจึง freeze/เปลี่ยน freeze")
    ap.add_argument("--unfreeze-when", required=True, help="เงื่อนไขที่จะปลด freeze")
    ap.add_argument(
        "--scope",
        default=(
            "เฉพาะตรรกะการให้คะแนนและการตัดสิน (app/security/*) — "
            "generator และ harness ของการทดลอง **ไม่** ถูก freeze "
            "เพราะต้องแก้เพื่อเพิ่มโปรไฟล์ผู้ใช้"
        ),
    )
    a = ap.parse_args()

    files = current_fingerprint()
    rec = {
        "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "reason": a.reason,
        "scope": a.scope,
        "unfreeze_when": a.unfreeze_when,
        "hash_method": "sha256 ของไฟล์หลัง normalize CRLF -> LF",
        "files": files,
    }

    # ต่อประวัติ ไม่เขียนทับ — เหตุผลของการ freeze ครั้งก่อนอาจยังไม่ถูก commit
    # ถ้าเขียนทับตรง ๆ เหตุผลนั้นจะหายไปจากทุกที่ (เคยเกิดจริง 16 ก.ย. 2569)
    history = []
    if RECORD.exists():
        prev = json.loads(RECORD.read_text(encoding="utf-8"))
        history = list(prev.get("history") or [])
        if not history:
            history.append(
                {
                    "frozen_at": prev.get("frozen_at"),
                    "git_commit": prev.get("git_commit"),
                    "reason": prev.get("reason"),
                    "files_changed": [],
                }
            )
        old_files = prev.get("files") or {}
        changed = sorted(k for k in files if old_files.get(k) != files[k])
    else:
        changed = sorted(files)
    history.append(
        {
            "frozen_at": rec["frozen_at"],
            "git_commit": rec["git_commit"],
            "reason": rec["reason"],
            "files_changed": changed,
        }
    )
    rec["history"] = history
    RECORD.write_text(
        json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"เขียนบันทึก freeze ลง {RECORD} ({len(rec['files'])} ไฟล์)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
