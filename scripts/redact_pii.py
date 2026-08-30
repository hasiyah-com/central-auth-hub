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

# โฮสต์/IP ของ production — ไม่ใช่ PII ของบุคคล แต่ repo สาธารณะไม่ควรประกาศเป้า
# ค่าจริงอยู่ในไฟล์ที่ gitignore เท่านั้น (หลักการเดียวกับ roster_v2.json)
# ถ้าเขียนไว้ในสคริปต์นี้ = ค่าจริงขึ้น git ไปพร้อมเครื่องมือที่ควรจะล้างมัน
HOSTS_FILE = ROOT / "ml-service" / "data" / "redact_hosts.json"
# อีเมลที่พบในประวัติแต่ไม่อยู่ใน roster (คนที่เลิกใช้ระบบ / ข้อมูลตัวอย่างรุ่นเก่า)
# roster ครอบคลุมแค่ 5 จาก 12 อีเมลที่อยู่ในประวัติจริง — ขาดไฟล์นี้ = rewrite แล้วยังเหลือ PII
EXTRA_FILE = ROOT / "ml-service" / "data" / "redact_extra.json"


def extra_emails() -> list[tuple[str, str]]:
    if not EXTRA_FILE.exists():
        return []
    d = json.loads(EXTRA_FILE.read_text(encoding="utf-8"))
    return [(k, v) for k, v in d.items() if not k.startswith("_")]


def host_replacements() -> list[tuple[str, str]]:
    if not HOSTS_FILE.exists():
        return []
    d = json.loads(HOSTS_FILE.read_text(encoding="utf-8"))
    return [(k, v) for k, v in d.items() if not k.startswith("_")]


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


def rule_specs() -> list[tuple[str, str, str, bool]]:
    """คืน [(kind, pattern, replacement, is_regex)] — แหล่งความจริงเดียวของ mapping.

    ใช้ทั้งการล้างไฟล์ปัจจุบัน (compile เป็น regex) และการเขียนไฟล์กฎให้
    git-filter-repo ตอน rewrite ประวัติ — mapping ต้องมาจากที่เดียวกัน
    ไม่งั้น HEAD กับประวัติจะถูกแทนคนละแบบ
    """
    if not ROSTER.exists():
        sys.exit(f"ไม่พบ roster ที่ {ROSTER.relative_to(ROOT)} — ต้องมีเพื่อสร้าง mapping")
    roster: dict[str, str] = json.loads(ROSTER.read_text(encoding="utf-8"))

    emails, locals_, ids = [], [], []
    for email, rep in extra_emails():
        emails.append((email, rep))
        lp = email.split("@")[0]
        # local-part เดี่ยวๆ ต้องแทนด้วย — เฉพาะกรณีที่ค่าแทนเป็น alias (คนจริง)
        # ข้อมูลตัวอย่างสมมติ (somchai.j ฯลฯ) ไม่ต้อง ไม่ใช่ PII และมีจุดคั่นอยู่แล้ว
        if len(lp) >= 5 and re.fullmatch(r"U\d+@.*", rep):
            locals_.append((lp, rep.split("@")[0]))
    for alias, email in roster.items():
        if not email or email.endswith(SYNTHETIC_DOMAINS):
            continue
        lp = email.split("@")[0]
        emails.append((email, f"{alias}@{PLACEHOLDER_DOMAIN}"))
        if lp.isdigit() and len(lp) >= 8:
            ids.append((lp, alias))
        elif len(lp) >= 5:
            locals_.append((lp, alias))

    out: list[tuple[str, str, str, bool]] = []
    # ลำดับสำคัญ: อีเมลเต็มก่อน ไม่งั้น local-part จะกินส่วนหน้าแล้วเหลือโดเมนจริง
    for val, rep in sorted(emails, key=lambda x: -len(x[0])):
        out.append(("อีเมล", val, rep, False))
    for val, rep in sorted(ids, key=lambda x: -len(x[0])):
        out.append(("รหัสตัวเลข", val, rep, False))
    for val, rep in sorted(locals_, key=lambda x: -len(x[0])):
        out.append(
            (
                "local-part",
                rf"(?<![A-Za-z0-9._-]){re.escape(val)}(?![A-Za-z0-9._-])",
                rep,
                True,
            )
        )
    # โฮสต์ production — ไม่ได้อยู่ใน roster ต้องระบุแยก
    for host, rep in host_replacements():
        out.append(("โฮสต์", host, rep, False))
    return out


def load_rules() -> list[tuple[re.Pattern, str, str]]:
    """คืน [(pattern, ค่าแทน, คำอธิบายชนิด)] เรียงจากยาวไปสั้น.

    ต้องแทนอีเมลเต็มก่อน local-part เสมอ ไม่งั้น local-part จะกินส่วนหน้าของอีเมล
    แล้วเหลือ `U03@<โดเมนจริง>` ซึ่งยังชี้กลับไปหาโดเมนของคนจริงอยู่
    """
    rules = []
    for kind, pat, rep, is_rx in rule_specs():
        rules.append((re.compile(pat if is_rx else re.escape(pat), re.I), rep, kind))
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
    ap.add_argument(
        "--emit-rules",
        type=Path,
        help="เขียนไฟล์กฎรูปแบบ git-filter-repo (--replace-text/--replace-message) "
        "แล้วจบ — ไฟล์ที่ได้มีค่าจริง ห้าม commit",
    )
    args = ap.parse_args()

    if args.emit_rules:
        lines = []
        for kind, pat, rep, is_rx in rule_specs():
            # filter-repo: literal เป็นค่าเริ่มต้น · regex ต้องนำหน้าด้วย regex:
            lines.append(f"{'regex:' if is_rx else ''}{pat}==>{rep}")
        args.emit_rules.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
        print(f"เขียนกฎ {len(lines)} ข้อ -> {args.emit_rules}")
        print("⚠️ ไฟล์นี้มีค่าจริง — เก็บนอก repo และลบทิ้งหลังใช้")
        return 0

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
