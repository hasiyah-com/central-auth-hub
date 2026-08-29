"""แทน PII ของผู้ใช้จริงในไฟล์ที่ git ติดตาม ด้วย alias ตามธรรมเนียมของโปรเจค.

โปรเจคนี้ใช้ alias `U01`–`U12` แทนผู้ใช้จริงมาตลอด โดยเก็บ mapping ไว้ที่
`ml-service/data/roster_v2.json` (gitignored) — สคริปต์นี้ทำให้ไฟล์ที่ commit แล้ว
สอดคล้องกับธรรมเนียมนั้นย้อนหลัง

แทน 3 รูปแบบ (จาก mapping เดียวกัน จึงสาวกลับได้ด้วย roster ถ้าจำเป็น):
    อีเมลเต็ม        someone@<โดเมนจริง>   -> U03@example.invalid
    local-part เดี่ยว someone              -> U03
    รหัสตัวเลขยาว     66xxxxxxxx           -> U07   (รวมที่ฝังใน hostname)

`.invalid` เป็น TLD ที่ RFC 2606 สงวนไว้ — ส่งอีเมลไปไม่ถึงใครแน่นอน

Run:
    python scripts/redact_pii.py            # dry-run: บอกว่าจะแก้อะไรบ้าง
    python scripts/redact_pii.py --apply    # แก้จริง
    python scripts/redact_pii.py --apply --paths a.md b.py

**ไม่พิมพ์ค่าจริง** — รายงานเป็นจำนวนครั้งต่อไฟล์เท่านั้น
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROSTER = ROOT / "ml-service" / "data" / "roster_v2.json"
SYNTHETIC_DOMAINS = ("@hub.local", "@uni.ac.th")
PLACEHOLDER_DOMAIN = "example.invalid"

SKIP_EXT = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".pdf",
    ".zip",
    ".gz",
    ".mmdb",
    ".pyc",
    ".so",
    ".dll",
    ".exe",
    ".svg",
    ".docx",
    ".pptx",
    ".xlsx",
    ".pkl",
    ".joblib",
}
SKIP_PATH = re.compile(
    r"(^|/)(node_modules|\.next|__pycache__|venv|dist|build|vendor)/|\.min\.js$"
)


def load_rules() -> list[tuple[re.Pattern, str, str]]:
    """คืน [(pattern, ค่าแทน, คำอธิบายชนิด)] เรียงจากยาวไปสั้น.

    ต้องแทนอีเมลเต็มก่อน local-part เสมอ ไม่งั้น local-part จะกินส่วนหน้าของอีเมล
    แล้วเหลือ `U03@<โดเมนจริง>` ซึ่งยังชี้กลับไปหาโดเมนของคนจริงอยู่
    """
    if not ROSTER.exists():
        sys.exit(f"ไม่พบ roster ที่ {ROSTER.relative_to(ROOT)} — ต้องมีเพื่อสร้าง mapping")
    roster: dict[str, str] = json.loads(ROSTER.read_text(encoding="utf-8"))

    emails, locals_, ids = [], [], []
    for alias, email in roster.items():
        if not email or email.endswith(SYNTHETIC_DOMAINS):
            continue
        lp = email.split("@")[0]
        emails.append((email, f"{alias}@{PLACEHOLDER_DOMAIN}"))
        if lp.isdigit() and len(lp) >= 8:
            ids.append((lp, alias))
        elif len(lp) >= 5:
            locals_.append((lp, alias))

    rules = []
    for val, rep in sorted(emails, key=lambda x: -len(x[0])):
        rules.append((re.compile(re.escape(val), re.I), rep, "อีเมล"))
    # รหัสตัวเลข: substring ล้วน เพราะถูกฝังใน hostname (s<รหัส>db-postgres)
    for val, rep in sorted(ids, key=lambda x: -len(x[0])):
        rules.append((re.compile(re.escape(val)), rep, "รหัสตัวเลข"))
    for val, rep in sorted(locals_, key=lambda x: -len(x[0])):
        rules.append(
            (
                re.compile(
                    rf"(?<![A-Za-z0-9._-]){re.escape(val)}(?![A-Za-z0-9._-])", re.I
                ),
                rep,
                "local-part",
            )
        )
    return rules


def tracked() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    ).stdout
    keep = []
    for rel in out.splitlines():
        if not rel.strip() or SKIP_PATH.search(rel):
            continue
        p = ROOT / rel
        if p.suffix.lower() in SKIP_EXT or not p.is_file():
            continue
        keep.append(p)
    return keep


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="แก้ไฟล์จริง (ไม่ใส่ = dry-run)")
    ap.add_argument("--paths", nargs="*", help="จำกัดเฉพาะไฟล์ที่ระบุ")
    args = ap.parse_args()

    rules = load_rules()
    print(f"กฎการแทนที่: {len(rules)} ข้อ (จาก roster — ไม่พิมพ์ค่า)\n")

    files = [ROOT / p for p in args.paths] if args.paths else tracked()
    total_files = total_hits = 0
    for p in files:
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new, per_kind = text, {}
        for rx, rep, kind in rules:
            new, n = rx.subn(rep, new)
            if n:
                per_kind[kind] = per_kind.get(kind, 0) + n
        if not per_kind:
            continue
        total_files += 1
        total_hits += sum(per_kind.values())
        detail = " · ".join(f"{k} {v}" for k, v in sorted(per_kind.items()))
        print(f"  {p.relative_to(ROOT).as_posix()}  →  {detail}")
        if args.apply:
            p.write_text(new, encoding="utf-8")

    print(f"\n{'แก้แล้ว' if args.apply else 'จะแก้'} {total_files} ไฟล์ · {total_hits} จุด")
    if not args.apply and total_files:
        print("รันซ้ำด้วย --apply เพื่อแก้จริง")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
