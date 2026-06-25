"""Claude Code PostToolUse hook — reminder ลำดับ log_action → commit → raise (B6).

ตรวจไฟล์ใน hub/backend/app/routers/**.py:
ถ้ามี `raise HTTPException` หรือ `db.commit()` ใน diff → print reminder

Advisory only — exit 0
"""

import json
import sys
from pathlib import PurePosixPath


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0

    if event.get("tool_name") not in ("Write", "Edit"):
        return 0

    file_path = event.get("tool_input", {}).get("file_path", "")
    norm = str(PurePosixPath(file_path.replace("\\", "/")))

    # เฉพาะ router files (จุดที่ B6 มักเกิด)
    if "/hub/backend/app/routers/" not in norm or not norm.endswith(".py"):
        return 0

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return 0

    has_raise = "raise HTTPException" in content
    has_log_action = "log_action(" in content

    if has_raise and has_log_action:
        print(
            f"[audit-order] {file_path}: ตรวจสอบลำดับ log_action -> db.commit() -> raise HTTPException "
            "(bug B6) — มิฉะนั้น rollback กิน audit",
            file=sys.stderr,
        )

    if has_raise and not has_log_action:
        print(
            f"[audit-order] {file_path}: มี raise HTTPException แต่ไม่มี log_action — "
            "failure paths ต้อง log ด้วย (bug B7)",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
