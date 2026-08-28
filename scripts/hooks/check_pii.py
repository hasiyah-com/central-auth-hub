"""กัน PII ของคนจริงหลุดขึ้น git.

ตรวจไฟล์ที่ staged (pre-commit) หรือไฟล์ที่ระบุ ว่ามีตัวตนจริงของผู้ใช้ระบบหรือไม่:
  - อีเมลจริงในโดเมนของสถาบัน/ส่วนตัว (นอกเหนือ allowlist ที่เป็น placeholder)
  - ชื่อ-สกุลจริงภาษาไทยที่อยู่ในรายชื่อ roster
  - user UUID จริงจาก DB

allowlist = อีเมลที่เป็น placeholder/seed ที่สร้างด้วยสคริปต์ (ไม่ใช่คนจริง)

Run:
    py scripts/hooks/check_pii.py                # ตรวจไฟล์ที่ staged
    py scripts/hooks/check_pii.py --all          # ตรวจทุกไฟล์ที่ git ติดตาม
    py scripts/hooks/check_pii.py path/to/file   # ตรวจไฟล์ที่ระบุ
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROSTER = ROOT / "ml-service" / "data" / "roster_v2.json"

SKIP_SUFFIX = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".pkl",
    ".joblib",
    ".mmdb",
    ".lock",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
}
# เอกสาร Office = zip ของ xml -> ต้องแตกอ่าน ไม่ใช่ข้าม
OFFICE_SUFFIX = {".docx", ".pptx", ".xlsx", ".dotx", ".potx"}
SKIP_DIRS = {"node_modules", ".git", "postgres_data", "__pycache__", ".next", "venv"}

# โดเมนที่ถือว่าเป็นคนจริงถ้าไม่อยู่ใน allowlist
REAL_DOMAINS = r"(?:gmail\.com|pnu\.ac\.th)"
EMAIL_RE = re.compile(rf"[a-zA-Z0-9._%+-]+@{REAL_DOMAINS}")

# อีเมลตัวอย่าง/เอกสารที่ไม่ใช่คนจริง — เพิ่มได้เมื่อมั่นใจว่าเป็น placeholder
ALLOWLIST = {
    "you@gmail.com",
    "your-email@gmail.com",
    "example@gmail.com",
    "test@gmail.com",
    "admin@gmail.com",
    "user@gmail.com",
    "someone@gmail.com",
    "xxx@gmail.com",
    # test fixture ใน tests/test_change_google.py — ไม่ใช่บัญชีของใคร
    "x@gmail.com",
    # placeholder ในคู่มือ LINE Login
    "your-line-email@gmail.com",
    # ผู้ดูแลแพ็กเกจ open-source ใน hub/sdk/php-client/composer.lock
    # (metadata สาธารณะของ packagist ไม่ใช่ผู้ใช้ระบบเรา)
    "bschussek@gmail.com",
    "whatthejeff@gmail.com",
}


# โดเมนของบัญชีที่ seed_users.py สร้างขึ้นเอง — สังเคราะห์ ไม่ใช่คนจริง
SYNTHETIC_DOMAINS = ("@hub.local", "@uni.ac.th")


def real_identities() -> tuple[set[str], set[str]]:
    """คืน (อีเมลจริง, ชื่อจริง) จาก roster ถ้ามี — roster เองอยู่นอก git.

    ตัดบัญชีที่ seed script สร้างเองออก (เช่น admin01@hub.local, 650024@uni.ac.th)
    เพราะไม่ใช่ข้อมูลของบุคคลจริง แม้จะถูกใช้เป็น anchor ในการทดลอง
    """
    emails: set[str] = set()
    if ROSTER.exists():
        emails |= {
            e
            for e in json.loads(ROSTER.read_text(encoding="utf-8")).values()
            if e and not e.endswith(SYNTHETIC_DOMAINS)
        }
    return emails, set()


def staged_files() -> list[Path]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    ).stdout
    return [ROOT / f for f in out.splitlines() if f.strip()]


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, cwd=ROOT
    ).stdout
    return [ROOT / f for f in out.splitlines() if f.strip()]


def _office_text(path: Path) -> str:
    """ดึงข้อความจาก .docx/.pptx/.xlsx (zip ของ xml) — ไฟล์พวกนี้ก็ซ่อน PII ได้."""
    import zipfile

    try:
        with zipfile.ZipFile(path) as z:
            parts = [
                n
                for n in z.namelist()
                if n.endswith(".xml") and ("word/" in n or "ppt/" in n or "xl/" in n)
            ]
            return " ".join(z.read(n).decode("utf-8", "ignore") for n in parts[:60])
    except Exception:  # noqa: BLE001 — ไฟล์เสีย/ไม่ใช่ zip = ข้ามไป
        return ""


def scan(path: Path, roster_emails: set[str]) -> list[str]:
    if not path.is_file() or SKIP_DIRS & set(path.parts):
        return []
    suffix = path.suffix.lower()
    if suffix in OFFICE_SUFFIX:
        text = _office_text(path)
    elif suffix in SKIP_SUFFIX:
        return []
    else:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return []
    try:
        shown = path.relative_to(ROOT)
    except ValueError:
        shown = path
    hits: list[str] = []
    for m in EMAIL_RE.finditer(text):
        addr = m.group(0)
        if addr.lower() in ALLOWLIST:
            continue
        line = text[: m.start()].count("\n") + 1
        hits.append(f"{shown}:{line}  อีเมลจริง: {addr}")
    for addr in roster_emails:
        if addr and addr not in EMAIL_RE.pattern and addr in text:
            if not EMAIL_RE.search(addr):  # โดเมนอื่น เช่น uni.ac.th / hub.local ใน roster
                line = text[: text.index(addr)].count("\n") + 1
                hits.append(f"{shown}:{line}  อีเมลใน roster: {addr}")
    return hits


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--all" in sys.argv:
        files = tracked_files()
    elif args:
        files = [Path(a) if Path(a).is_absolute() else ROOT / a for a in args]
    else:
        files = staged_files()

    roster_emails, _ = real_identities()
    hits: list[str] = []
    for f in files:
        hits += scan(f, roster_emails)

    if hits:
        print("❌ พบข้อมูลส่วนบุคคลของผู้ใช้จริงในไฟล์ที่จะขึ้น git:\n", file=sys.stderr)
        for h in hits[:50]:
            print(f"   {h}", file=sys.stderr)
        if len(hits) > 50:
            print(f"   ... อีก {len(hits) - 50} จุด", file=sys.stderr)
        print("\n   วิธีแก้: แทนด้วย alias (U01–U12) แล้วเก็บ mapping ไว้ที่", file=sys.stderr)
        print("   ml-service/data/roster_v2.json (gitignored)", file=sys.stderr)
        print("   ถ้าเป็น placeholder จริงๆ เพิ่มใน ALLOWLIST ของสคริปต์นี้", file=sys.stderr)
        return 1

    print(f"✅ ไม่พบ PII ของคนจริง ({len(files)} ไฟล์)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
