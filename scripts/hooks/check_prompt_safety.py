"""Claude Code UserPromptSubmit hook — warn ถ้า prompt มี keyword ที่อาจขัด security model.

ไม่ block — แค่ inject context warning ให้ Claude เห็น แล้วถาม user
"""

import json
import sys


# pattern keyword (lowercased) ที่ขัดต่อ CLAUDE.md security model
RISKY_KEYWORDS = [
    "disable audit",
    "skip security",
    "remove auth",
    "bypass rbac",
    "bypass auth",
    "without auth",
    "no audit log",
    "ปิด audit",
    "ข้าม security",
    "ข้าม rbac",
    "ลบ depends",
    "no-verify",
    "--no-verify",
]


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0

    prompt = (event.get("prompt") or "").lower()
    matched = [kw for kw in RISKY_KEYWORDS if kw in prompt]

    if matched:
        # stdout ของ UserPromptSubmit hook → injected เข้า context ของ Claude
        print(
            "[security-reminder] Prompt มี keyword ที่อาจขัด security model "
            f"ของโปรเจค: {matched}. "
            "ตรวจสอบ CLAUDE.md → 'Security non-negotiables' ก่อนทำตาม. "
            "ถ้าเป็น intentional security testing ให้ confirm กับ user ก่อน."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
