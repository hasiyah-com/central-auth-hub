"""pre-commit hook — ปฏิเสธไฟล์บีบอัดและไฟล์ที่เก็บ key ทุกชนิด.

ที่มา (17 ก.ย. 2569): `hub/backend.zip` มี private key ตัวเดียวกับที่ระบบใช้อยู่
`detect-private-key` อ่านเนื้อไฟล์ข้อความ จึงมองไม่เห็นของที่อยู่ในไฟล์บีบอัด
และไฟล์ key แบบ binary (p12/pfx) ก็ไม่มีบรรทัดหัวของ PEM ให้จับ

ไฟล์ Office (.docx/.pptx/.xlsx) เป็น zip ภายใน แต่ไม่ถูกกัน เพราะเป็นเอกสารที่
ตั้งใจ commit และไม่ใช่ช่องทางที่ใช้ห่อโค้ดหรือ key
"""

import re
import sys
from pathlib import PurePosixPath

BLOCK_RE = re.compile(
    r"\.(zip|rar|7z|tar|tgz|gz|bz2|xz|zst|p12|pfx|key)$",
    re.IGNORECASE,
)


def main(argv: list[str]) -> int:
    blocked = []
    for path in argv[1:]:
        norm = str(PurePosixPath(path.replace("\\", "/")))
        if BLOCK_RE.search(norm):
            blocked.append(norm)

    if blocked:
        print(
            "BLOCKED — ห้าม commit ไฟล์บีบอัดหรือไฟล์ key "
            "(อาจมี private key หรือ .env ซ่อนอยู่ข้างใน):",
            file=sys.stderr,
        )
        for p in blocked:
            print(f"  - {p}", file=sys.stderr)
        print(
            "\nวิธีแก้: `git restore --staged <file>` แล้วเก็บไฟล์นอก repo",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
