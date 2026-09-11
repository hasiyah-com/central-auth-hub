#!/usr/bin/env bash
# เขียน git history ใหม่เพื่อลบ PII ก่อนเปิด repo เป็นสาธารณะ
#
# ย้อนกลับไม่ได้ — commit hash เปลี่ยนทุกตัว ต้อง force push ทุก branch/tag
# สคริปต์นี้ backup ให้ก่อนเสมอ และ "ไม่ push ให้เอง" (หยุดก่อนขั้น push)
#
# ครอบคลุม 4 ชั้นที่ PII ซ่อนอยู่ได้:
#   1. เนื้อไฟล์ text            -> --replace-text
#   2. เนื้อไฟล์ Office (zip)     -> --blob-callback (replace-text แตะ zip ไม่ได้)
#   3. commit / tag message      -> --replace-message
#   4. author / committer email  -> --mailmap
#
# ใช้:  bash scripts/pii/rewrite_history.sh
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
DIR="$(cd scripts/pii && pwd)"
REPL="$DIR/replacements.txt"
MAILMAP="$DIR/mailmap.txt"
export REDACTED_DOCX="$DIR/SDLC_DBLC_Report_CentralAuthHub.redacted.docx"
DOCX_OID="95919d8c73dccd85cde0106ccf62dd7200511d6a"  # pragma: allowlist secret (git object id ไม่ใช่ secret)
BACKUP="../central-auth-hub-BACKUP-$(date +%Y%m%d-%H%M%S)"

echo "== 0. ตรวจก่อนเริ่ม =========================================="
if [ -n "$(git status --porcelain)" ]; then
  echo "working tree ยังไม่สะอาด — commit หรือ stash ให้หมดก่อน"
  git status --short | head -20
  exit 1
fi
for f in "$REPL" "$MAILMAP" "$REDACTED_DOCX"; do
  [ -f "$f" ] || { echo "ไม่พบ $f"; exit 1; }
done

# filter-repo อาจไม่ได้ลงเป็น git subcommand (Windows/pip --user)
if git filter-repo --version >/dev/null 2>&1; then
  FR=(git filter-repo)
elif command -v git-filter-repo >/dev/null 2>&1; then
  FR=(git-filter-repo)
elif [ -x "$HOME/AppData/Roaming/Python/Python313/Scripts/git-filter-repo.exe" ]; then
  FR=("$HOME/AppData/Roaming/Python/Python313/Scripts/git-filter-repo.exe")
else
  echo "หา git-filter-repo ไม่เจอ — pip install git-filter-repo"; exit 1
fi
echo "   tree สะอาด · ไฟล์ครบ · ใช้: ${FR[*]}"

echo
echo "== 1. สำรองข้อมูล (ทำก่อนเสมอ) =============================="
mkdir -p "$BACKUP"
git bundle create "$BACKUP/full-history.bundle" --all
git for-each-ref --format='%(refname) %(objectname)' > "$BACKUP/refs-before.txt"
git remote -v > "$BACKUP/remotes.txt"
echo "   backup -> $BACKUP"
echo "     กู้คืน: git clone $BACKUP/full-history.bundle <โฟลเดอร์ใหม่>"

echo
echo "== 2. เขียน history ใหม่ ====================================="
CB=$(cat <<'PYCB'
oid = blob.original_id
if isinstance(oid, bytes):
    oid = oid.decode()
if oid == "95919d8c73dccd85cde0106ccf62dd7200511d6a":  # pragma: allowlist secret
    import os, pathlib
    blob.data = pathlib.Path(os.environ["REDACTED_DOCX"]).read_bytes()
PYCB
)
"${FR[@]}" --force \
  --replace-text "$REPL" \
  --replace-message "$REPL" \
  --mailmap "$MAILMAP" \
  --blob-callback "$CB"
echo "   rewrite เสร็จ"

echo
echo "== 3. เก็บกวาด object เก่าในเครื่อง ==========================="
git reflog expire --expire=now --all
git gc --prune=now --quiet
echo "   ลบ object ที่ไม่ reachable แล้ว"

echo
echo "== 4. ตรวจผล ================================================"
python scripts/pii/verify_history.py || {
  echo; echo "ยังพบ PII — อย่า push · กู้คืนได้จาก $BACKUP"; exit 1; }

echo
echo "== เสร็จขั้น local — ขั้นต่อไปต้องทำเอง ======================="
cat <<'NEXT'
  filter-repo ลบ remote ทิ้งเพื่อกัน push พลาด ต้องใส่กลับเอง:

    git remote add origin https://github.com/hasiyah-com/central-auth-hub.git

  ต้อง force push *ทุก branch และ tag* — เหลือ branch เก่าบน GitHub
     แม้อันเดียว commit ที่มี PII จะยัง reachable

    git push origin --force --all
    git push origin --force --tags

  แล้วลบ branch บน GitHub ที่ไม่มีในเครื่องแล้ว (เช่น claude/* เก่า)

  ก่อนเปิด public: GitHub ยังเก็บ object เก่าไว้ (cached views / PR / fork)
  ให้ติดต่อ GitHub Support ขอ garbage-collect ฝั่ง server ก่อน
    https://support.github.com/   แจ้งว่า rewrote history เพื่อลบ sensitive data
NEXT
