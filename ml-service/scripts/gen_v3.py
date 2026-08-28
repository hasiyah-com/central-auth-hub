"""Generator V3 — episode-based normal + dev/final attack split (กัน experimental overfitting).

แก้ 2 ปัญหาของ V2:

  1. **timeline 3,200 วัน** — V2 สร้าง 5,000 event เป็นเส้นเวลาต่อเนื่อง 8.8 ปี (ไม่สมจริง)
     V3 แบ่งเป็น **episode ละ ~50 event ใน 20-30 วัน** · reset rolling state ทุก episode ·
     sequence window ห้ามข้าม episode -> ความหนาแน่น ~2 login/วัน โดยไม่มีประวัติยาวผิดธรรมชาติ

  2. **ใช้ attack ชุดเดียวเลือก config แล้ววัดผลซ้ำ** = experimental overfitting
     V3 แยก **development attack** (เลือก config/ฟีเจอร์) ออกจาก **final attack** (วัดครั้งเดียว)
     โดย final ใช้ parameter range / รูปแบบต่างจาก dev

ขนาดต่อคน (12 คน/seed):
    train pool 5,000 · validation 1,000 · final normal test 1,000
    dev attack 40 · final attack 40   (obvious 20 / subtle 10 / campaign 10 ต่อชุด)

learning curve ใช้ **nested subset**: Train-50 ⊂ 100 ⊂ 500 ⊂ 1000 ⊂ 5000
(validation/test ชุดเดิมทุกขนาด — ห้ามแบ่งใหม่ต่อขนาด)
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

ML = Path(__file__).resolve().parent
sys.path.insert(0, str(ML))
import build_profiles_v2 as BP  # noqa: E402
import features_v2 as FE  # noqa: E402

EPISODE_EVENTS = 50  # 1 episode = 50 event
EPISODE_DAYS = 25  # ในช่วง ~25 วัน -> ~2 login/วัน
EPISODE_STRIDE_DAYS = 400  # ระยะห่าง "บนปฏิทิน" ระหว่าง episode (แค่ให้ timestamp ไม่ชนกัน)

TRAIN_POOL = 5000
VAL_N = 1000
TEST_N = 1000
LC_SIZES = [50, 100, 500, 1000, 5000]

# dev / final ใช้ parameter range คนละชุด (กันเลือก config ให้ตรง test)
DEV, FINAL = "dev", "final"


def _episode(p: dict, ident: dict, rng, ep_index: int, n_events: int) -> list[dict]:
    """1 episode — ใช้เครื่องมือของ V2 แต่จำกัดช่วงเวลาเป็น EPISODE_DAYS."""
    saved_start, saved_days, saved_rows = BP.START, BP.DAYS, p.get("rows")
    BP.START = saved_start + timedelta(days=ep_index * EPISODE_STRIDE_DAYS)
    BP.DAYS = EPISODE_DAYS
    p = dict(p)
    p["rows"] = n_events
    try:
        rows = BP.gen_normal(p, ident, "staggered", rng)
    finally:
        BP.START, BP.DAYS = saved_start, saved_days
        if saved_rows is not None:
            p["rows"] = saved_rows
    for r in rows:
        r["episode"] = ep_index
    return rows


def gen_normal_episodes(p: dict, ident: dict, rng, total: int) -> list[list[dict]]:
    """คืน list ของ episode (แต่ละ episode คือ list ของ row เรียงเวลา)."""
    eps, made = [], 0
    i = 0
    while made < total:
        n = min(EPISODE_EVENTS, total - made)
        eps.append(_episode(p, ident, rng, i, n))
        made += n
        i += 1
    return eps


def features_by_episode(episodes: list[list[dict]], carry: dict | None = None):
    """สกัดฟีเจอร์แบบ reset rolling state ทุก episode แต่คงความรู้ระยะยาว (seen sets/โปรไฟล์เวลา)."""
    carry = carry if carry is not None else {}
    out = []
    for ep in episodes:
        out.append(FE._normal_features_incremental(ep, carry=carry))
    return out, carry


# ── attack: dev / final ใช้ parameter คนละชุด ───────────────────────────────────
def _tweak_for_final(p: dict) -> dict:
    """เปลี่ยน parameter ของโปรไฟล์เล็กน้อยสำหรับ final attack -> รูปแบบไม่ซ้ำ dev."""
    q = dict(p)
    q["hour_peaks"] = [(h + 3) % 24 for h in p["hour_peaks"]]
    q["dur"] = (p["dur"][0] * 0.8, p["dur"][1])
    return q


def gen_attack_pack(
    p: dict, ident: dict, rng, variant: str, ep_index: int = 0
) -> list[dict]:
    """obvious 20 + subtle 10 + campaign ต่อคน (นับเฉพาะ row_kind=attack).

    ต้องวางบนปฏิทินของ **episode สุดท้าย** ไม่งั้น gap เทียบ history จะติดลบ
    (attack เกิดก่อน history) -> velocity rule ยิงมั่วจน recall = 100%
    """
    src = p if variant == DEV else _tweak_for_final(p)
    saved_start, saved_days = BP.START, BP.DAYS
    BP.START = saved_start + timedelta(days=ep_index * EPISODE_STRIDE_DAYS)
    BP.DAYS = EPISODE_DAYS
    try:
        rows = BP.gen_attacks(src, ident, rng)  # obvious 20 + context
        for _ in range(2):  # subtle 2 รอบ -> ~10 (5 family × 2)
            rows += BP.gen_subtle_attacks(src, ident, rng)
        if variant == DEV:
            rows += BP.gen_campaign_attacks(src, ident, rng)  # 2 campaign × 5 phase
        else:
            # final: campaign รูปแบบใหม่ที่ไม่ได้ใช้ตอนเลือกฟีเจอร์ (หลบแกนของ Config F)
            rows += BP.gen_unseen_campaigns(src, ident, rng)
    finally:
        BP.START, BP.DAYS = saved_start, saved_days
    for r in rows:
        r["variant"] = variant
    return rows


def _camp_like_in_window(p, ident, rng, ep_index):
    """campaign-like normal บนปฏิทินของ episode สุดท้าย (label=0 แต่ต้องคำนวณฟีเจอร์แบบเดียวกัน)."""
    saved_start, saved_days = BP.START, BP.DAYS
    BP.START = saved_start + timedelta(days=ep_index * EPISODE_STRIDE_DAYS)
    BP.DAYS = EPISODE_DAYS
    try:
        rows = BP.gen_campaign_like_normal(p, ident, rng)
    finally:
        BP.START, BP.DAYS = saved_start, saved_days
    return [{**r, "row_kind": "attack"} for r in rows]


def build_seed(users_xlsx: Path, seed: int):
    """สร้างข้อมูลครบ 1 seed ตามสเปค — คืน dict[alias] = {...}."""
    import json

    BP.SEED = seed
    rng = BP.random.Random(seed)
    roster = json.loads((BP.DATA / "roster_v2.json").read_text(encoding="utf-8"))
    ids = BP.load_identities(users_xlsx)

    users = {}
    for spec in BP.SPEC:
        p = dict(spec)
        p["email"] = roster.get(p["alias"], "")
        ident = ids[p["email"]]

        total = TRAIN_POOL + VAL_N + TEST_N
        eps = gen_normal_episodes(p, ident, rng, total)
        feats, carry = features_by_episode(eps)

        flat_rows = [r for ep in eps for r in ep]
        flat_ft = [f for ep in feats for f in ep]
        cols = FE.FEATURES

        def vecs(sl):
            return [[float(f[c]) for c in cols] for f in sl]

        tr_rows, tr_ft = flat_rows[:TRAIN_POOL], flat_ft[:TRAIN_POOL]
        va_ft = flat_ft[TRAIN_POOL : TRAIN_POOL + VAL_N]
        te_rows = flat_rows[TRAIN_POOL + VAL_N : total]
        te_ft = flat_ft[TRAIN_POOL + VAL_N : total]

        # attack features:
        #   trusted  = history "ทั้งหมด" -> ความรู้ระยะยาว (เครื่อง/ระบบที่เคยใช้, โปรไฟล์เวลา)
        #              ถ้าใช้แค่ episode สุดท้าย is_new_device/subsystem จะยิงมั่ว (attack ดูใหม่หมด)
        #   observed = episode สุดท้าย + context -> rolling state (velocity/gap/concurrent)
        #              ไม่ข้าม episode ตามกฎเดียวกับ normal
        all_hist = sorted(flat_rows, key=lambda r: r["created_at"])
        last_i = len(eps) - 1
        last_ep = eps[last_i]

        def attack_feats(rows):
            out = []
            for r in sorted(rows, key=lambda x: x["created_at"]):
                if r["row_kind"] != "attack":
                    continue
                trusted = all_hist
                ctx = [
                    x
                    for x in rows
                    if x["row_kind"] == "context"
                    and x["scenario"] == r["scenario"]
                    and x["created_at"] < r["created_at"]
                ]
                observed = sorted(last_ep + ctx, key=lambda x: x["created_at"])
                out.append((r, FE.compute(r, trusted, observed)))
            return out

        users[p["alias"]] = dict(
            train_raw=tr_rows,
            train_ft=vecs(tr_ft),
            train_episodes=[len(e) for e in eps],
            val_ft=vecs(va_ft),
            test=list(zip(te_rows, vecs(te_ft))),
            dev_attacks=attack_feats(gen_attack_pack(p, ident, rng, DEV, last_i)),
            final_attacks=attack_feats(gen_attack_pack(p, ident, rng, FINAL, last_i)),
            camp_like=attack_feats(_camp_like_in_window(p, ident, rng, last_i)),
            episode_of=[i for i, e in enumerate(eps) for _ in e],
        )
    return users


def nested_subset(u: dict, size: int):
    """Train-50 ⊂ 100 ⊂ 500 ⊂ 1000 ⊂ 5000 — ตัดจากหัวเสมอ."""
    return u["train_raw"][:size], u["train_ft"][:size]


def episode_bounds(u: dict, size: int):
    """คืน index เริ่มต้นของแต่ละ episode ภายใน train subset (sequence window ห้ามข้าม)."""
    eo = u["episode_of"][:size]
    bounds, cur = [], None
    for i, e in enumerate(eo):
        if e != cur:
            bounds.append(i)
            cur = e
    return bounds + [size]


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    us = build_seed(a.users, a.seed)
    n = len(us)
    tr = sum(len(x["train_ft"]) for x in us.values())
    va = sum(len(x["val_ft"]) for x in us.values())
    te = sum(len(x["test"]) for x in us.values())
    da = sum(len(x["dev_attacks"]) for x in us.values())
    fa = sum(len(x["final_attacks"]) for x in us.values())
    cl = sum(len(x["camp_like"]) for x in us.values())
    eps = us[next(iter(us))]["train_episodes"]
    print(f"ผู้ใช้ {n} คน · episode {len(eps)} ชุด (ละ {eps[0]} event / {EPISODE_DAYS} วัน)")
    print(f"  train pool  {tr:>6} ({tr // n}/คน)")
    print(f"  validation  {va:>6} ({va // n}/คน)")
    print(f"  final test  {te:>6} ({te // n}/คน)")
    print(f"  dev attack  {da:>6} ({da // n}/คน)")
    print(f"  final attack{fa:>6} ({fa // n}/คน)")
    print(f"  camp-like normal {cl:>4} ({cl // n}/คน)")
    print(f"  รวม {tr + va + te + da + fa + cl:>6} เหตุการณ์/seed")
    import numpy as np

    g = np.array(
        [
            v[FE.FEATURES.index("log_minutes_since_last_login")]
            for v in us["U01"]["train_ft"]
        ]
    )
    print(
        f"\n  gap_log (U01): median {np.median(g):.2f} · max {g.max():.2f} "
        f"(ถ้า episode ทำงาน ไม่ควรมีค่าโดดจากช่วงข้าม episode)"
    )
