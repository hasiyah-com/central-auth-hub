"""pre-commit hook — reject ถ้า .env (ไม่ใช่ .env.example) อยู่ใน stage.

Cross-platform replacement สำหรับ bash one-liner — Windows-safe.
"""

import re
import sys
from pathlib import PurePosixPath


# pattern เดียวกับ check_secret_path.py (Claude Code hook)
# Block: .env, .env.local, .env.production, etc. (anything starting with .env)
# Allow: any file ending with .example / .sample / .template — so the regex
# allows .env.example AND .env.local.example AND .env.production.sample etc.
BLOCK_RE = re.compile(r"(^|/)\.env(\..+)?$")
ALLOW_RE = re.compile(r"\.(example|sample|template)$")


def main(argv: list[str]) -> int:
    blocked = []
    for path in argv[1:]:
        norm = str(PurePosixPath(path.replace("\\", "/")))
        if ALLOW_RE.search(norm):
            continue
        if BLOCK_RE.search(norm):
            blocked.append(norm)

    if blocked:
        print(
            "BLOCKED — ห้าม commit .env (ใช้ .env.example เป็น template แทน):",
            file=sys.stderr,
        )
        for p in blocked:
            print(f"  - {p}", file=sys.stderr)
        print(
            "\nวิธีแก้: `git restore --staged <file>` แล้วเพิ่มชื่อใน .gitignore",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
