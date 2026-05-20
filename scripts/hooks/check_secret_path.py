"""Claude Code PreToolUse hook — block Write/Edit ไปยังไฟล์ลับ.

ตรวจ tool_input.file_path ตาม pattern ใน CLAUDE.md "ห้าม commit":
- **/.env (ยกเว้น .env.example)
- **/*.pem, **/*.key
- **/keys/**
- **/postgres_data/**

Exit codes:
  0 = allow
  2 = block (Claude เห็น stderr message)
"""
import json
import re
import sys
from pathlib import PurePosixPath


BLOCK_PATTERNS = [
    re.compile(r"(^|/)\.env(\..+)?$"),     # .env, .env.local, .env.production — แต่ไม่ .env.example
    re.compile(r"\.pem$"),
    re.compile(r"\.key$"),
    re.compile(r"(^|/)keys/"),
    re.compile(r"(^|/)postgres_data/"),
]

# allow-list ที่ override block (template/example ปลอดภัย)
ALLOW_PATTERNS = [
    re.compile(r"\.env\.example$"),
    re.compile(r"\.env\.sample$"),
    re.compile(r"\.env\.template$"),
]


def is_blocked(file_path: str) -> tuple[bool, str]:
    # Normalize Windows backslash → forward slash สำหรับ regex match
    norm = str(PurePosixPath(file_path.replace("\\", "/")))

    for pat in ALLOW_PATTERNS:
        if pat.search(norm):
            return False, ""

    for pat in BLOCK_PATTERNS:
        if pat.search(norm):
            return True, pat.pattern

    return False, ""


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception as e:
        # malformed input → fail-open (ไม่ block) แต่ log
        print(f"check_secret_path: malformed event ({e})", file=sys.stderr)
        return 0

    tool_name = event.get("tool_name", "")
    if tool_name not in ("Write", "Edit", "NotebookEdit"):
        return 0

    file_path = event.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return 0

    blocked, pattern = is_blocked(file_path)
    if blocked:
        print(
            f"BLOCKED: '{file_path}' matches secret pattern '{pattern}'. "
            "ห้าม Claude แก้ไฟล์ลับ (CLAUDE.md: Prompt Defense Baseline). "
            "ถ้าต้องการ template ให้ใช้ .env.example แทน",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
