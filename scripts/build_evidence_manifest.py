"""สร้าง/ตรวจสอบ manifest ของชุดหลักฐานการทดลอง RBA (freeze ผลการทดลอง).

ทำไมต้องมี: ผลการทดลองจะถูกส่งให้ผู้เชี่ยวชาญตรวจ — ต้องพิสูจน์ได้ว่า "ตัวเลขที่อ้าง
มาจากไฟล์ชุดไหน ตอน commit ไหน ด้วย config/seed อะไร" และไฟล์ไม่ถูกแก้ย้อนหลัง

    python scripts/build_evidence_manifest.py            # สร้าง/อัปเดต manifest
    python scripts/build_evidence_manifest.py --verify   # ตรวจว่าไฟล์ยังตรง hash เดิม

--verify คืน exit code 1 ถ้ามีไฟล์เปลี่ยน/หาย → ใช้ใน CI หรือก่อนส่งหลักฐานได้

stdlib อย่างเดียว (เหมือน scripts/hooks/*) — รันได้ทุกเครื่องไม่ต้องลง dependency
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "hub" / "backend" / "tests" / "reports"
# manifest แต่ละรอบเป็นคนละไฟล์ — **ห้ามเขียนทับของเดิม** เพราะ tag เก่าอ้างไฟล์นั้นอยู่
# (เขียนทับ = หลักฐานของ freeze รอบก่อนหายไป ตรวจย้อนไม่ได้)
MANIFEST_DIR = ROOT / "docs"
MANIFEST_DEFAULT = MANIFEST_DIR / "RBA_EVIDENCE_MANIFEST_2026-09-01.md"

# ── ชุดหลักฐาน: รายงานการทดลอง (เรียงตามลำดับที่ทำจริง) ──
EVIDENCE_REPORTS = [
    "profiles_v2_2026-08-21.md",
    "rba_4layer_v2_2026-08-21.md",
    "learning_curve_v2_2026-08-21.md",
    "phase1_production_port_2026-08-21.md",
    "v7_generator_fix_2026-08-21.md",
    "v2_to_v7_version_sweep_2026-08-21.md",
    "model_version_decision_2026-08-21.md",
    "v8_verification_2026-08-23.md",
    "ablation_v8_vs_rule_2026-08-23.md",
    "tier1_rarity_behavior_2026-08-25.md",
    "tier2_cadence_signature_2026-08-25.md",
    "lc_4layer_2026-08-25.md",
    "l3_ownership_nocampaign_2026-08-25.md",
    "l3_campaign_2026-08-26.md",
    "l3_sequence_channel_2026-08-26.md",
    "l3_raw_vs_effective_2026-08-26.md",
    "exp_4layer_full_2026-08-26.md",
    "exp_l3_config_g_2026-08-26.md",
    "exp_lc_v3_2026-08-26.md",
    "exp_thr_and_l2_fix_2026-08-26.md",
    "exp_l3_window_2026-08-26.md",
    "exp_campaign_level_2026-08-26.md",
    "exp_final_synthetic_2026-08-26.md",
    "exp_final_gate_2026-08-26.md",
    "l3_service_split_2026-08-29.md",
    "l3_stability_2026-08-29.md",
    "l3_shadow_replay_2026-08-29.md",
    "l3_unified_2026-08-31.md",
]

# ── โค้ดที่ผลิตตัวเลข (harness ทดลอง + production ที่ถูกวัด) ──
EVIDENCE_CODE = [
    "ml-service/scripts/gen_v3.py",
    "ml-service/scripts/build_profiles_v2.py",
    "ml-service/scripts/features_v2.py",
    "ml-service/scripts/exp_final_gate.py",
    "ml-service/scripts/exp_campaign_level.py",
    "ml-service/scripts/exp_final_synthetic.py",
    "ml-service/scripts/exp_lc_v3.py",
    "ml-service/scripts/exp_4layer_full.py",
    "ml-service/scripts/lc_l3_sequence.py",
    "ml-service/scripts/lc_l3_ownership.py",
    "ml-service/scripts/lc_run_4layer.py",
    "ml-service/app/sequence.py",
    "hub/backend/app/security/l3_sequence.py",
    "hub/backend/app/security/rule_engine.py",
    "hub/backend/app/security/behavior_profiling.py",
    "hub/backend/app/security/risk_aggregator.py",
    "hub/backend/app/security/risk_engine.py",
    "hub/backend/app/services/l3_sequence_client.py",
    "hub/backend/scripts/l3_shadow_replay.py",
    "hub/backend/tests/test_l3_stability.py",
    "hub/backend/tests/test_l3_access_monitoring_split.py",
    # รอบ 31 ส.ค. 2026 — L3 orchestrator เดียว + ถอด IForest ออกจาก access (B66)
    "ml-service/app/l3_unified.py",
    "ml-service/app/model.py",
    "ml-service/app/main.py",
    "hub/backend/app/security/iforest_scorer.py",
    "hub/backend/tests/test_l3_unified.py",
]

# ── configuration ที่ล็อกไว้: ดึงจาก source จริง ไม่ hardcode ในเอกสาร ──
CONFIG_SOURCE = ROOT / "hub" / "backend" / "app" / "security" / "l3_sequence.py"
CONFIG_KEYS = [
    "DIMS",
    "WINDOW",
    "MAX_HISTORY",
    "CAL_FPR",
    "EXTREME_FPR",
    "TIER_DIAGNOSTIC",
    "TIER_WARN",
    "TIER_CHALLENGE",
    "MODEL_VERSION",
]

SEEDS = {
    "train / validation (dev)": "42, 43, 44, 45, 46",
    "final gate evaluation": "101, 102, 103, 104, 105",
    "IsolationForest random_state": "42 (คงที่ทุก fit)",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return "(ไม่พร้อมใช้งาน)"


def read_config() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in CONFIG_SOURCE.read_text(encoding="utf-8").splitlines():
        for k in CONFIG_KEYS:
            if line.startswith(f"{k} ="):
                out[k] = line.split("=", 1)[1].split("#")[0].strip()
    return out


def collect() -> list[tuple[str, str, int]]:
    """คืน [(relative path, sha256, ขนาดไบต์)] ของหลักฐานทุกไฟล์ที่มีอยู่จริง."""
    rows = []
    for name in EVIDENCE_REPORTS:
        p = REPORTS / name
        if p.exists():
            rows.append((p.relative_to(ROOT).as_posix(), sha256(p), p.stat().st_size))
    for rel in EVIDENCE_CODE:
        p = ROOT / rel
        if p.exists():
            rows.append((rel, sha256(p), p.stat().st_size))
    return rows


def missing() -> list[str]:
    out = [n for n in EVIDENCE_REPORTS if not (REPORTS / n).exists()]
    out += [c for c in EVIDENCE_CODE if not (ROOT / c).exists()]
    return out


def build(MANIFEST: Path) -> None:
    rows = collect()
    cfg = read_config()
    head, short, branch = (
        git("rev-parse", "HEAD"),
        git("rev-parse", "--short", "HEAD"),
        git("branch", "--show-current"),
    )
    dirty = git("status", "--porcelain")
    L = [
        "# ชุดหลักฐานการทดลอง RBA — Evidence Manifest (freeze)",
        "",
        f"**สร้างเมื่อ:** {date.today().isoformat()} · **สร้างโดย:** `scripts/build_evidence_manifest.py`",
        "",
        "เอกสารนี้ freeze ผลการทดลอง 4-Layer RBA เพื่อให้ตรวจสอบย้อนกลับได้ —",
        "ตัวเลขที่อ้างในรายงาน/thesis ทุกตัวสาวกลับมาที่ commit + ไฟล์ + hash ในนี้ได้",
        "",
        "**ตรวจสอบว่าหลักฐานยังไม่ถูกแก้:**",
        "",
        "```bash",
        "python scripts/build_evidence_manifest.py --verify",
        "```",
        "",
        "---",
        "",
        "## 1. Provenance (commit)",
        "",
        "| รายการ | ค่า |",
        "|---|---|",
        f"| commit SHA (เต็ม) | `{head}` |",
        f"| commit SHA (สั้น) | `{short}` |",
        f"| branch | `{branch}` |",
        f"| working tree ตอนสร้าง manifest | {'สะอาด' if not dirty else 'มีไฟล์ที่ยังไม่ commit (ดู §5)'} |",
        f"| จำนวนไฟล์หลักฐาน | {len(rows)} |",
        "",
        "> ⚠️ commit SHA ด้านบนคือ **commit ก่อนหน้า** ตอน generate — SHA ของ freeze commit เอง",
        "> บันทึกไว้ที่ §5 (เขียนเพิ่มหลัง commit เสร็จ เพราะ SHA คำนวณจากเนื้อหาไฟล์รวมทั้ง manifest)",
        "",
        "## 2. Configuration ที่ล็อก (ดึงจาก source จริง)",
        "",
        f"อ่านจาก `{CONFIG_SOURCE.relative_to(ROOT).as_posix()}` ณ commit ข้างต้น",
        "",
        "| ค่าคงที่ | ค่า | ความหมาย |",
        "|---|---|---|",
    ]
    meaning = {
        "DIMS": "จำนวนมิติ residual ต่อเหตุการณ์",
        "WINDOW": "ความยาว rolling window (เหตุการณ์)",
        "MAX_HISTORY": "จำนวน residual สูงสุดที่เก็บ/ใช้ต่อคน",
        "CAL_FPR": "threshold anomaly = quantile(1 − ค่านี้) → p99.9",
        "EXTREME_FPR": "threshold extreme → p99.97",
        "TIER_DIAGNOSTIC": "history ขั้นต่ำที่เริ่มให้คะแนน (log อย่างเดียว)",
        "TIER_WARN": "history ขั้นต่ำที่ขึ้นธง monitoring l3_investigate ได้",
        "TIER_CHALLENGE": "history ขั้นต่ำที่บันทึก shadow_decision=would_challenge",
        "MODEL_VERSION": "รหัสเวอร์ชันโมเดลที่เขียนลงทุก contract",
    }
    for k in CONFIG_KEYS:
        L.append(f"| `{k}` | `{cfg.get(k, '(ไม่พบ)')}` | {meaning[k]} |")
    L += [
        "",
        "**สถาปัตยกรรมที่ล็อกคู่กัน:** residual 6 มิติ × [mean, slope, ptp] = 18 อินพุต ·",
        "per-user IsolationForest (`n_estimators=100`, `contamination=0.02`) ·",
        "L3 = แกน monitoring ล้วน (`normal` / `l3_investigate`) — ไม่แตะ access decision",
        "",
        "**ครอบคลุม L3 ทั้งสองมุมมองตั้งแต่ 31 ส.ค. 2026** (B66) — เดิม point view",
        "(IForest 23 ฟีเจอร์) ยังบวกคะแนนเข้า `aggregate()` ได้ถึง +0.40 ทั้งที่การทดลอง",
        "ทุกชุดวัดด้วย `NEUTRAL` (= 0) · วัดจากข้อมูลจริง 1,024 sessions พบว่ากระทบ",
        "**128 ครั้ง (12.5%) ของการตัดสิน** รวม block 22 ครั้ง → แก้ด้วย",
        "`iforest_scorer.monitoring_only()` ทำให้ production ตรงกับตัวเลขที่วัดไว้",
        "(ไม่ได้ปรับโมเดล/threshold ใดๆ — ดู `l3_unified_2026-08-31.md`)",
        "",
        "ค่าคงที่ชุดเดียวกันนี้ต้องตรงกับ `ml-service/app/sequence.py` —",
        "บังคับด้วย `tests/test_l3_sequence_client.py::test_constants_parity_hub_vs_ml_service`",
        "",
        "## 3. Seeds",
        "",
        "| ชุด | seeds |",
        "|---|---|",
    ]
    for k, v in SEEDS.items():
        L.append(f"| {k} | `{v}` |")
    L += [
        "",
        "**กติกาที่ยึด:** ชุด evaluation (101–105) ถูกสร้างใหม่ทั้ง normal และ attack",
        "โมเดลไม่เคยเห็น · รันครั้งเดียว · **ห้ามปรับ threshold/โมเดล/ฟีเจอร์จากผลชุดนี้**",
        "",
        "## 4. Hash ของไฟล์หลักฐาน (SHA-256)",
        "",
        "### 4.1 รายงานการทดลอง",
        "",
        "| ไฟล์ | ขนาด (ไบต์) | SHA-256 |",
        "|---|---|---|",
    ]
    for rel, h, size in rows:
        if rel.startswith("hub/backend/tests/reports/"):
            L.append(f"| `{rel.split('/')[-1]}` | {size:,} | `{h}` |")
    L += [
        "",
        "### 4.2 โค้ดที่ผลิตตัวเลข (harness ทดลอง + production ที่ถูกวัด)",
        "",
        "| ไฟล์ | ขนาด (ไบต์) | SHA-256 |",
        "|---|---|---|",
    ]
    for rel, h, size in rows:
        if not rel.startswith("hub/backend/tests/reports/"):
            L.append(f"| `{rel}` | {size:,} | `{h}` |")
    miss = missing()
    if miss:
        L += ["", "**ไฟล์ที่ประกาศไว้แต่ไม่พบ:**", ""] + [f"- `{m}`" for m in miss]
    L += [
        "",
        "## 5. Freeze commit",
        "",
        "<!-- FREEZE_COMMIT -->",
        "_(เติมหลัง commit — ดู `git log --oneline -1` และ `git tag -l`)_",
        "",
        "## 6. ข้อมูลที่ไม่อยู่ใน git (โดยตั้งใจ)",
        "",
        "ตามข้อกำหนด **ข้อมูลจริงห้ามขึ้น git เด็ดขาด** — ไฟล์ต่อไปนี้อยู่ใน `.gitignore`",
        "และ **ไม่ได้** อยู่ใน manifest นี้:",
        "",
        "| ประเภท | ที่อยู่ | เหตุผล |",
        "|---|---|---|",
        "| โปรไฟล์ผู้ใช้จริง (anchor) | `ml-service/data/*.xlsx`, `real_*.csv` | PII — อีเมล/ชื่อ/แผนก |",
        "| login ที่ generate จาก anchor | `ml-service/data/user_logins*.csv` | สาวกลับหาบุคคลได้ |",
        "| ฟีเจอร์/โมเดลรายคน | `ml-service/data/*.csv`, `ml-service/models/` | derived จาก PII |",
        "| residual history | Redis `l3resid:{user_id}` | runtime เท่านั้น ไม่ persist ลงไฟล์ |",
        "",
        "ผู้ตรวจที่ต้องการทำซ้ำต้องใช้ anchor ของตนเอง แล้วรัน harness ตาม §4.2",
        "(ทุกสคริปต์รับ `--users` และ `--seeds` เป็นอาร์กิวเมนต์)",
        "",
    ]
    # rstrip กัน blank line ท้ายไฟล์ -> hook "fix end of files" ไม่ต้องแก้ซ้ำทุกรอบ
    MANIFEST.write_text("\n".join(L).rstrip() + "\n", encoding="utf-8")
    print(f"manifest -> {MANIFEST.relative_to(ROOT)}")
    print(f"  ไฟล์หลักฐาน {len(rows)} ไฟล์ · commit {short} · branch {branch}")
    if miss:
        print(f"  ⚠️ ไม่พบ {len(miss)} ไฟล์: {', '.join(miss[:5])}")


def verify(MANIFEST: Path) -> int:
    """เทียบ hash ปัจจุบันกับที่บันทึกใน manifest — exit 1 ถ้าไม่ตรง."""
    if not MANIFEST.exists():
        print("ไม่พบ manifest — รันโดยไม่ใส่ --verify ก่อน")
        return 1
    recorded = dict(
        re.findall(
            r"^\| `([^`]+)` \| [\d,]+ \| `([0-9a-f]{64})` \|$",
            MANIFEST.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    )
    if not recorded:
        print("manifest ไม่มีรายการ hash")
        return 1
    bad, gone = [], []
    for rel, h, _ in collect():
        key = (
            rel.split("/")[-1] if rel.startswith("hub/backend/tests/reports/") else rel
        )
        if key not in recorded:
            gone.append(f"{key} (ไม่ได้บันทึกไว้ใน manifest)")
        elif recorded[key] != h:
            bad.append(key)
    present = {
        (r.split("/")[-1] if r.startswith("hub/backend/tests/reports/") else r)
        for r, _, _ in collect()
    }
    gone += [f"{k} (หายไปจาก repo)" for k in recorded if k not in present]
    print(f"ตรวจ {len(recorded)} รายการ")
    for b in bad:
        print(f"  ❌ เปลี่ยนแปลง: {b}")
    for g in gone:
        print(f"  ⚠️ {g}")
    if not bad and not gone:
        print("  ✅ ทุกไฟล์ตรงกับ manifest")
        return 0
    return 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verify", action="store_true", help="ตรวจ hash แทนการสร้างใหม่")
    ap.add_argument(
        "--manifest",
        type=Path,
        default=MANIFEST_DEFAULT,
        help="ไฟล์ manifest (ค่าเริ่มต้น = รอบล่าสุด) — ใส่ของรอบเก่าเพื่อตรวจย้อนได้",
    )
    args = ap.parse_args()
    target = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    sys.exit(verify(target) if args.verify else (build(target) or 0))
