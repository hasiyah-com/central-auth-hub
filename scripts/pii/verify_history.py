"""ตรวจว่า git history ไม่มี PII ของคนจริงเหลืออยู่ — รันหลัง rewrite.

ตรวจ 4 ชั้น:
  1. blob ที่เป็น text        -> หาอีเมลจริงตรงๆ
  2. blob ที่เป็น Office (zip) -> แตกอ่าน xml ข้างใน (replace-text แตะไม่ได้)
  3. commit/tag message       -> ต้องใช้ --replace-message ถึงจะโดนแก้
  4. author/committer ของทุก commit

exit 0 = สะอาด · exit 1 = ยังมีเหลือ (อย่า push)

Run: py scripts/pii/verify_history.py
"""

from __future__ import annotations

import io
import re
import subprocess
import sys
import zipfile
from collections import defaultdict

REAL = re.compile(rb"[a-zA-Z0-9._%+-]+@(?:gmail\.com|pnu\.ac\.th)")
# อีเมลที่ไม่ใช่ผู้ใช้ระบบ — placeholder + ผู้ดูแลแพ็กเกจ open-source ใน composer.lock
ALLOW = {
    b"you@gmail.com",
    b"your-email@gmail.com",
    b"example@gmail.com",
    b"test@gmail.com",
    b"admin@gmail.com",
    b"user@gmail.com",
    b"someone@gmail.com",
    b"xxx@gmail.com",
    b"x@gmail.com",
    b"your-line-email@gmail.com",
    b"bschussek@gmail.com",
    b"whatthejeff@gmail.com",
}


def _paths() -> dict[str, set[str]]:
    out = subprocess.run(
        ["git", "rev-list", "--objects", "--all"], capture_output=True
    ).stdout.decode("utf-8", "ignore")
    p: dict[str, set[str]] = defaultdict(set)
    for line in out.splitlines():
        a = line.split(" ", 1)
        if len(a) == 2:
            p[a[0]].add(a[1])
    return p


def scan_blobs() -> list[str]:
    paths = _paths()
    chk = subprocess.run(
        [
            "git",
            "cat-file",
            "--batch-all-objects",
            "--batch-check=%(objectname) %(objecttype) %(objectsize)",
        ],
        capture_output=True,
    ).stdout.decode()
    blobs = [
        (o, int(s))
        for o, t, s in (line.split() for line in chk.splitlines())
        if t == "blob" and int(s) < 60_000_000
    ]
    proc = subprocess.Popen(
        ["git", "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE
    )
    hits: list[str] = []
    for oid, size in blobs:
        proc.stdin.write((oid + "\n").encode())
        proc.stdin.flush()
        proc.stdout.readline()
        data = proc.stdout.read(size)
        proc.stdout.read(1)
        chunks = [data]
        if data.startswith(b"PK\x03\x04"):  # Office = zip -> ต้องแตกอ่าน
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    names = [n for n in z.namelist() if n.endswith(".xml")]
                    chunks.append(b" ".join(z.read(n) for n in names[:80]))
            except Exception:  # noqa: BLE001
                pass
        for chunk in chunks:
            for m in set(REAL.findall(chunk)):
                if m.lower() in ALLOW:
                    continue
                where = ", ".join(sorted(paths.get(oid, {"(unreachable)"})))
                hits.append(f"blob {oid[:10]} [{where}] -> {m.decode()}")
    proc.stdin.close()
    proc.wait()
    return hits


def scan_messages() -> list[str]:
    """commit/tag message ก็ซ่อนอีเมลได้ — ต้องใช้ --replace-message ถึงจะโดนแก้."""
    out = subprocess.run(
        ["git", "log", "--all", "--pretty=format:%H%x01%B%x02"], capture_output=True
    ).stdout.decode("utf-8", "ignore")
    hits = []
    for rec in out.split(chr(2)):
        if chr(1) not in rec:
            continue
        sha, body = rec.split(chr(1), 1)
        for m in set(REAL.findall(body.encode())):
            if m.lower() in ALLOW:
                continue
            hits.append(f"commit {sha.strip()[:10]} message -> {m.decode()}")
    return hits


def scan_authors() -> list[str]:
    out = subprocess.run(
        ["git", "log", "--all", "--pretty=format:%H%x09%ae%x09%ce"], capture_output=True
    ).stdout.decode("utf-8", "ignore")
    hits = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        sha, ae, ce = parts
        for who, addr in (("author", ae), ("committer", ce)):
            m = REAL.fullmatch(addr.encode())
            if m and addr.lower().encode() not in ALLOW:
                hits.append(f"commit {sha[:10]} {who} -> {addr}")
    return hits


def main() -> int:
    blob_hits = scan_blobs()
    msg_hits = scan_messages()
    author_hits = scan_authors()
    if blob_hits or msg_hits or author_hits:
        print("ยังพบ PII ใน history — ห้าม push", file=sys.stderr)
        for h in (blob_hits + msg_hits + author_hits)[:40]:
            print(f"   {h}", file=sys.stderr)
        total = len(blob_hits) + len(msg_hits) + len(author_hits)
        if total > 40:
            print(f"   ... อีก {total - 40} จุด", file=sys.stderr)
        return 1
    print("history สะอาด — blob (รวม Office) · commit message · author/committer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
