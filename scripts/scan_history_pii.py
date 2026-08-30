"""สแกน **ทุก blob ในประวัติ git** หา PII / ความลับที่เคยหลุดเข้าไป.

ต่างจาก `scripts/hooks/check_pii.py` ที่ตรวจเฉพาะไฟล์ปัจจุบัน — ไฟล์ที่ถูกลบไปแล้ว
ยังอยู่ในประวัติและกู้กลับมาได้ ถ้า repo จะเปิดสาธารณะต้องตรวจย้อนหลังทั้งหมด

ตรวจ 4 อย่าง:
  1. path ต้องห้าม  — .env / *.pem / keys/ / ไฟล์ข้อมูลจริง ที่เคยถูก commit
  2. อีเมลคนจริง    — โดเมนจริง (ไม่ใช่ placeholder/seed) + อีเมลใน roster
  3. ความลับ        — private key, JWT, API key, connection string ที่มีรหัสผ่าน
  4. เลขระบุตัวตน   — เบอร์โทรไทย, เลขบัตรประชาชน 13 หลัก

**ไม่พิมพ์ค่าจริงเต็มๆ** — mask ให้เหลือพอระบุชนิด (รายงานนี้อาจถูก commit เอง)

Run:
    python scripts/scan_history_pii.py                 # สแกนทั้งประวัติ
    python scripts/scan_history_pii.py --out report.md # เขียนรายงาน
    python scripts/scan_history_pii.py --refs HEAD     # เฉพาะ branch ปัจจุบัน

exit 1 ถ้าพบอะไร — ใช้เป็น gate ก่อนเปิด repo เป็นสาธารณะได้
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROSTER = ROOT / "ml-service" / "data" / "roster_v2.json"

# ── 1. path ที่ไม่ควรเคยอยู่ใน git เลย ──
FORBIDDEN_PATH = [
    # .env, .env.production ฯลฯ — แต่ *.example เป็น template ที่ commit ได้
    (re.compile(r"(^|/)\.env(\.[^/]*)?$"), "ไฟล์ .env (ความลับ)"),
    (re.compile(r"\.(pem|key|p12|pfx)$"), "ไฟล์กุญแจ/ใบรับรอง"),
    (re.compile(r"(^|/)keys/"), "โฟลเดอร์ keys/"),
    (re.compile(r"(^|/)postgres_data/"), "ข้อมูล Postgres ดิบ"),
    (
        re.compile(
            r"ml-service/data/(real_|user_logins|user_features|user_anomalies|roster_v2\.json)"
        ),
        "ข้อมูลผู้ใช้จริง/อนุพันธ์",
    ),
    (re.compile(r"\.(xlsx|xls)$"), "สเปรดชีต (อาจเป็น roster จริง)"),
    (re.compile(r"(^|/)models/.*\.(pkl|joblib)$"), "โมเดลที่เทรนจากข้อมูลจริง"),
]

# ── 2. อีเมล ──
REAL_DOMAINS = r"(?:gmail\.com|pnu\.ac\.th|hotmail\.com|outlook\.com|yahoo\.com)"
EMAIL_RE = re.compile(rf"[a-zA-Z0-9._%+-]+@{REAL_DOMAINS}")
ALLOWLIST = {
    "you@gmail.com",
    "your-email@gmail.com",
    "example@gmail.com",
    "test@gmail.com",
    "admin@gmail.com",
    "user@gmail.com",
    "someone@gmail.com",
    "xxx@gmail.com",
    "x@gmail.com",
    "your-line-email@gmail.com",
    "bschussek@gmail.com",
    "whatthejeff@gmail.com",  # maintainer ของ package สาธารณะ
    "noreply@anthropic.com",
}
SYNTHETIC_DOMAINS = ("@hub.local", "@uni.ac.th")

# ── 3. ความลับ ──
SECRET_RE = [
    (
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
        "private key",
    ),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
        "JWT ที่ลงนามแล้ว",
    ),
    (re.compile(r"\b(?:sk|rk)-[A-Za-z0-9]{20,}"), "API key รูปแบบ sk-/rk-"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key"),
    (re.compile(r"\bghp_[A-Za-z0-9]{30,}"), "GitHub token"),
    (
        re.compile(r"postgres(?:ql)?://[^\s:@/]+:[^\s@/]{6,}@"),
        "connection string ที่มีรหัสผ่าน",
    ),
    (re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{10,}"), "Google OAuth client secret"),
]

# ── 3b. โฮสต์/IP ของ production ──
# ไม่ใช่ PII ของบุคคล แต่ถ้า repo เป็นสาธารณะ = ประกาศเป้าให้สแกน
# จับเฉพาะบริบทที่เป็นโฮสต์จริงแน่ๆ (URL / sslip.io) ไม่จับเลข 4 ท่อนลอยๆ
# เพราะจะชนกับเลขเวอร์ชันเต็มไปหมด
_PRIVATE_IP = re.compile(
    r"^(?:10\.|127\.|0\.|169\.254\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)"
    r"|^(?:192\.0\.2\.|198\.51\.100\.|203\.0\.113\.)"  # ช่วงสำหรับเอกสาร RFC 5737
)


# IP สาธารณะที่เป็น fixture มาตรฐาน ไม่ใช่โฮสต์ของเรา
# 93.184.216.34 = example.com ของ IANA — ใช้ในเทส SSRF เพื่อแทน "public IP จริง"
# (ใช้ช่วง RFC 5737 แทนไม่ได้ เพราะ ipaddress ของ Python ถือว่าเป็น private
#  -> SSRF guard จะบล็อกด้วยเหตุผลอื่น เทสก็ไม่ได้ทดสอบสิ่งที่ตั้งใจ)
IP_ALLOWLIST = {"93.184.216.34", "93.184.215.14"}


def _public_ip(ip: str) -> bool:
    if ip in IP_ALLOWLIST:
        return False
    parts = ip.split(".")
    if len(parts) != 4 or any(not q.isdigit() or int(q) > 255 for q in parts):
        return False
    return not _PRIVATE_IP.match(ip)


HOST_RE = [
    (re.compile(r"(\d{1,3})-(\d{1,3})-(\d{1,3})-(\d{1,3})\.sslip\.io"), "sslip"),
    (re.compile(r"https?://(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"), "url"),
]


# ── 4. เลขระบุตัวตน (heuristic — ต้องกรอง false positive) ──
# ขอบเขตต้องกัน . และ - ด้วย ไม่งั้นทศนิยม/hash ในข้อมูลสังเคราะห์จะติดหมด
ID_RE = [
    (re.compile(r"(?<![\d.\-])0[689]\d{8}(?![\d.\-])"), "เบอร์โทรไทย"),
    # ขอบเขตกัน hex ด้วย — SHA-256 ในตาราง manifest มีช่วงตัวเลขล้วน 13 หลักได้
    (
        re.compile(r"(?<![0-9a-fA-F.\-])[1-8]\d{12}(?![0-9a-fA-F.\-])"),
        "เลขบัตรประชาชน 13 หลัก",
    ),
]


def looks_fake(num: str) -> bool:
    """เบอร์/เลขที่สร้างขึ้นเพื่อทดสอบ — เรียงต่อเนื่อง หรือใช้เลขซ้ำแทบทั้งชุด."""
    body = num[2:] if num.startswith("0") else num
    if len(set(body)) <= 3:  # 0810000000, 0811111111
        return True
    digits = [int(c) for c in body]
    # ลำดับต่อเนื่อง รวมที่วนกลับหลัก 0 (0834567890 -> ...789 0)
    if all((b - a) % 10 == 1 for a, b in zip(digits, digits[1:])):
        return True
    return False


# เอกสาร Office = zip ของ xml -> ต้องแตกอ่าน ไม่งั้น PII ในไฟล์พวกนี้หลุดสายตา
OFFICE_EXT = {".docx", ".pptx", ".xlsx", ".dotx", ".potx"}


def office_text(raw: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            parts = [
                n
                for n in z.namelist()
                if n.endswith(".xml") and ("word/" in n or "ppt/" in n or "xl/" in n)
            ]
            return " ".join(z.read(n).decode("utf-8", "ignore") for n in parts[:80])
    except Exception:  # noqa: BLE001
        return ""


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
}
SKIP_PATH = re.compile(r"(^|/)(node_modules|\.next|__pycache__|venv|dist|build)/")
# lock file ของ package manager = metadata สาธารณะ ไม่ใช่ข้อมูลผู้ใช้เรา
# lock file / vendor bundle = โค้ดสาธารณะของคนอื่น ไม่ใช่ข้อมูลผู้ใช้เรา
NOISE_PATH = re.compile(
    r"(package-lock\.json|composer\.lock|yarn\.lock|poetry\.lock)$"
    r"|(^|/)vendor/|\.min\.js$"
)
MAX_BLOB = 3_000_000
LOCALPARTS: set[str] = set()


def mask(value: str) -> str:
    """ปิดบังค่าจริง — เหลือพอระบุชนิด แต่เอาไปใช้ต่อไม่ได้."""
    if "@" in value:
        local, _, dom = value.partition("@")
        return f"{local[:2]}{'*' * max(len(local) - 2, 1)}@{dom}"
    return f"{value[:3]}{'*' * max(len(value) - 3, 1)}"


def roster_localparts(emails: set[str]) -> set[str]:
    """ส่วนหน้า @ ของอีเมลจริง — ถูกใช้เป็น "ชื่อผู้ใช้" ในรายงาน/hostname ได้

    เช่น รายงานที่เขียนว่า "ผู้ใช้ 5 คน: aaa, bbb, ccc" คือ PII เต็มๆ
    ทั้งที่ไม่มีเครื่องหมาย @ ให้ regex อีเมลจับ · ยาว >= 5 กัน false positive
    """
    out = set()
    for e in emails:
        lp = e.split("@")[0]
        if len(lp) >= 5:
            out.add(lp)
        # รหัสนักศึกษาที่เป็น local-part เช่น 66xxxxxxxx ถูกเอาไปใส่ hostname ด้วย
        if lp.isdigit() and len(lp) >= 8:
            out.add(lp)
    return out


def roster_emails() -> set[str]:
    if not ROSTER.exists():
        return set()
    try:
        return {
            e
            for e in json.loads(ROSTER.read_text(encoding="utf-8")).values()
            if e and not e.endswith(SYNTHETIC_DOMAINS)
        }
    except Exception:  # noqa: BLE001
        return set()


def git(*args: str, binary: bool = False):
    r = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=not binary,
        encoding=None if binary else "utf-8",
        errors=None if binary else "ignore",
    )
    return r.stdout


def all_blobs(refs: list[str]) -> dict[str, set[str]]:
    """คืน {blob_sha: {path, ...}} จากทุก commit ใน refs ที่ระบุ."""
    out: dict[str, set[str]] = defaultdict(set)
    raw = git("rev-list", "--objects", *refs)
    for line in raw.splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[1]:
            out[parts[0]].add(parts[1])
    return out


def blob_types(shas: list[str]) -> dict[str, tuple[str, int]]:
    """คืน {sha: (type, size)} ด้วย batch เดียว (เร็วกว่ายิงทีละอัน)."""
    p = subprocess.run(
        ["git", "cat-file", "--batch-check"],
        cwd=ROOT,
        input="\n".join(shas),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    out = {}
    for line in p.stdout.splitlines():
        f = line.split()
        if len(f) == 3 and f[1] == "blob":
            out[f[0]] = (f[1], int(f[2]))
    return out


def scan_text(
    text: str, roster: set[str], locals_: set[str] | None = None
) -> list[tuple[str, str]]:
    """คืน [(ชนิด, ค่าที่ mask แล้ว)]."""
    hits = []
    for lp in locals_ or LOCALPARTS:
        # รหัสตัวเลขยาว (รหัสนักศึกษา) ถูกฝังใน hostname ได้ เช่น s6660...db-postgres
        # -> ค้นแบบ substring · ตัวอักษรใช้ขอบเขตคำเพื่อกัน false positive
        pat = (
            re.escape(lp)
            if lp.isdigit()
            else rf"(?<![A-Za-z0-9._-]){re.escape(lp)}(?![A-Za-z0-9._-])"
        )
        if re.search(pat, text):
            hits.append(("ชื่อผู้ใช้/รหัส (local-part ของอีเมลจริง)", mask(lp)))
    for m in EMAIL_RE.finditer(text):
        a = m.group(0)
        if a.lower() not in ALLOWLIST:
            hits.append(("อีเมลคนจริง", mask(a)))
    for a in roster:
        if a in text and not EMAIL_RE.search(a):
            hits.append(("อีเมลใน roster", mask(a)))
    for rx, label in SECRET_RE:
        if rx.search(text):
            hits.append(("ความลับ", label))
    for rx, kind in HOST_RE:
        for m in rx.finditer(text):
            ip = ".".join(m.groups()) if kind == "sslip" else m.group(1)
            if _public_ip(ip):
                hits.append(("โฮสต์ production", f"{kind}: {mask(ip)}"))
                break
    for rx, label in ID_RE:
        for m in rx.finditer(text):
            if looks_fake(m.group(0)):
                continue
            hits.append(("เลขระบุตัวตน", f"{label}: {mask(m.group(0))}"))
            break
    # dedup โดยคงลำดับ
    seen, out = set(), []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def current_hits(path: str, roster: set[str]) -> set[tuple[str, str]]:
    """hit ที่อยู่ใน blob **ของ HEAD** จริงๆ.

    ต้องแยกระดับ hit ไม่ใช่ระดับไฟล์ — ไฟล์เดียวอาจมี PII เก่าในประวัติ (ล้างแล้ว)
    ปนกับ PII ที่ยังเหลือ ถ้าจัดกลุ่มทั้งไฟล์ จะรายงานของที่ล้างแล้วว่ายังอยู่
    """
    raw = subprocess.run(
        ["git", "cat-file", "blob", f"HEAD:{path}"], cwd=ROOT, capture_output=True
    )
    if raw.returncode != 0:
        return set()
    ext = Path(path).suffix.lower()
    body = (
        office_text(raw.stdout)
        if ext in OFFICE_EXT
        else raw.stdout.decode("utf-8", "ignore")
    )
    return set(scan_text(body, roster))


def in_current_tree(path: str, roster: set[str]) -> bool:
    """blob **ที่ HEAD** ยังมีปัญหาไหม.

    ต้องดูที่ HEAD ไม่ใช่ working tree — สิ่งที่คนอื่นเห็นเมื่อ clone คือสิ่งที่ commit แล้ว
    (working tree อาจแก้ไว้แล้วแต่ยังไม่ commit = ยังไม่ปลอดภัย)
    """
    raw = subprocess.run(
        ["git", "cat-file", "blob", f"HEAD:{path}"], cwd=ROOT, capture_output=True
    )
    if raw.returncode != 0:
        return False
    ext = Path(path).suffix.lower()
    body = (
        office_text(raw.stdout)
        if ext in OFFICE_EXT
        else raw.stdout.decode("utf-8", "ignore")
    )
    return bool(scan_text(body, roster))


def scan_commit_messages(refs, roster):
    """PII ใน commit message — filter-repo ที่ลบไฟล์อย่างเดียวจะไม่ล้างส่วนนี้."""
    sep = "===PII-REC-SEP==="
    raw = git("log", *refs, f"--format=%H%n%B{sep}")
    out = []
    for rec in raw.split(sep):
        rec = rec.strip()
        if not rec:
            continue
        sha, _, body = rec.partition(chr(10))
        for kind, val in scan_text(body, roster):
            out.append((sha.strip()[:7], kind, val))
    return out


def commits_touching(path: str) -> list[str]:
    raw = git("log", "--all", "--oneline", "--follow", "--", path)
    return raw.splitlines()[:5]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--refs", nargs="*", default=["--all"], help="ref ที่จะสแกน (default: ทุก ref)"
    )
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    global LOCALPARTS
    roster = roster_emails()
    LOCALPARTS = roster_localparts(roster)
    print(f"local-part ที่เฝ้า: {len(LOCALPARTS)} รายการ")
    print(f"roster (สำหรับเทียบ, ไม่พิมพ์ค่า): {len(roster)} รายการ", flush=True)

    blobs = all_blobs(args.refs)
    print(f"blob ทั้งหมดในประวัติ: {len(blobs):,}", flush=True)

    # ── 1. path ต้องห้าม ──
    path_hits: list[tuple[str, str]] = []
    for paths in blobs.values():
        for p in paths:
            if SKIP_PATH.search(p):
                continue
            if p.endswith(".example"):  # template ที่ตั้งใจ commit
                continue
            for rx, label in FORBIDDEN_PATH:
                if rx.search(p):
                    path_hits.append((p, label))
    path_hits = sorted(set(path_hits))

    # ── 2-4. เนื้อหา ──
    candidates = []
    for sha, paths in blobs.items():
        p = next(iter(paths))
        if SKIP_PATH.search(p) or NOISE_PATH.search(p):
            continue
        ext = Path(p).suffix.lower()
        if ext in SKIP_EXT and ext not in OFFICE_EXT:
            continue
        candidates.append(sha)

    meta = blob_types(candidates)
    scan_list = [s for s in candidates if s in meta and meta[s][1] <= MAX_BLOB]
    print(f"blob ที่ต้องอ่านเนื้อหา: {len(scan_list):,}", flush=True)

    content_hits: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for i, sha in enumerate(scan_list, 1):
        if i % 2000 == 0:
            print(f"  ... {i:,}/{len(scan_list):,}", flush=True)
        raw = subprocess.run(
            ["git", "cat-file", "blob", sha], cwd=ROOT, capture_output=True
        ).stdout
        ext = Path(next(iter(blobs[sha]))).suffix.lower()
        text = office_text(raw) if ext in OFFICE_EXT else raw.decode("utf-8", "ignore")
        found = scan_text(text, roster)
        if found:
            for p in sorted(blobs[sha]):
                for kind, val in found:
                    content_hits[p].append((kind, val))

    # ── รายงาน ──
    L = [
        "# ตรวจ PII / ความลับ ในประวัติ git ทั้งหมด",
        "",
        f"**สร้างโดย:** `scripts/scan_history_pii.py` · **ขอบเขต:** {' '.join(args.refs)}",
        f"**blob ที่ตรวจ:** {len(scan_list):,} จากทั้งหมด {len(blobs):,}",
        "",
        "> ค่าที่พบถูก **mask** ไว้ — รายงานนี้บอกว่ามีปัญหาที่ไหน ไม่ใช่บอกค่าจริง",
        "",
        "## 1. ไฟล์ต้องห้ามที่เคยอยู่ในประวัติ",
        "",
    ]
    if path_hits:
        L += ["| path | ชนิด | commit ที่แตะ (ล่าสุด 5) |", "|---|---|---|"]
        for p, label in path_hits:
            cs = " · ".join(c.split()[0] for c in commits_touching(p)) or "—"
            L.append(f"| `{p}` | {label} | {cs} |")
    else:
        L.append("✅ ไม่พบ — ไม่มีไฟล์ต้องห้ามในประวัติเลย")

    L += ["", "## 2. เนื้อหาที่เข้าข่าย PII / ความลับ", ""]
    now, hist = {}, {}
    for path in sorted(content_hits):
        cur = current_hits(path, roster)
        old = [h for h in dict.fromkeys(content_hits[path]) if h not in cur]
        if cur:
            now[path] = sorted(cur)
        if old:
            hist[path] = old

    def _rows(d: dict) -> list[str]:
        out = ["| ไฟล์ | ชนิด | ค่า (mask) |", "|---|---|---|"]
        for path in sorted(d):
            seen = set()
            for kind, val in d[path]:
                if (kind, val) in seen:
                    continue
                seen.add((kind, val))
                out.append(f"| `{path}` | {kind} | `{val}` |")
        return out

    L += [
        "### 2.1 🔴 ยังอยู่ในไฟล์ปัจจุบัน (เห็นทันทีที่เปิด repo)",
        "",
    ]
    L += _rows(now) if now else ["✅ ไม่พบ — ไฟล์ปัจจุบันสะอาด"]
    L += [
        "",
        "### 2.2 🟠 อยู่แค่ในประวัติ (ไฟล์ปัจจุบันล้างแล้ว แต่ commit เก่ายังกู้ได้)",
        "",
    ]
    L += _rows(hist) if hist else ["✅ ไม่พบ"]

    msg_hits = scan_commit_messages(args.refs, roster)
    total = len(path_hits) + len(content_hits) + len(msg_hits)
    L += ["", "## 2.3 PII ใน commit message", ""]
    if msg_hits:
        L += ["| commit | ชนิด | ค่า (mask) |", "|---|---|---|"]
        seen = set()
        for sha, kind, val in msg_hits:
            if (sha, kind, val) in seen:
                continue
            seen.add((sha, kind, val))
            L.append(f"| `{sha}` | {kind} | `{val}` |")
        L += [
            "",
            "> ⚠️ `git filter-repo --invert-paths` ล้างเฉพาะไฟล์ — commit message",
            "> ต้องใช้ `--message-callback` แยกต่างหาก",
        ]
    else:
        L.append("✅ ไม่พบ")

    L += [
        "",
        "## 3. สรุป",
        "",
        f"- ไฟล์ต้องห้ามในประวัติ: **{len(path_hits)}**",
        f"- 🔴 ไฟล์ปัจจุบันที่ยังมี PII: **{len(now)}**",
        f"- 🟠 ไฟล์ที่สะอาดแล้วแต่ประวัติยังค้าง: **{len(hist)}**",
        f"- commit message ที่มี PII: **{len(set(msg_hits))}**",
        "",
        (
            "✅ **ประวัติสะอาด** — เปิด repo เป็นสาธารณะได้โดยไม่ต้อง rewrite history"
            if total == 0
            else "❌ **ต้องจัดการก่อนเปิดสาธารณะ** — ดู §4"
        ),
        "",
    ]
    if total:
        L += [
            "## 4. วิธีจัดการ",
            "",
            "ลบไฟล์ออกจากประวัติทั้งหมด (ต้อง force-push และผู้ที่ clone ไว้ต้อง clone ใหม่):",
            "",
            "```bash",
            "pip install git-filter-repo",
            "git filter-repo --invert-paths --path <ไฟล์> --path <ไฟล์>",
            "```",
            "",
            "**หลังลบแล้ว: หมุนความลับทุกตัวที่เคยหลุด** (JWT key, OAuth secret, DB password)",
            "— ถือว่ารั่วแล้วเสมอ เพราะประวัติอาจถูก clone/cache ไปก่อนหน้านี้",
            "",
        ]
    report = "\n".join(L).rstrip() + "\n"
    print("\n" + report)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"-> {args.out}")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
