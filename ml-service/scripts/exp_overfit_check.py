"""ทดสอบ overfitting ของ Config F — unseen campaign + campaign-like normal.

ข้อกังวล: campaign เดิม drift ใน cadence/scope/subsystem = แกนของ Config F พอดี
-> ผลเดิม (unique 16.3%) พิสูจน์ไม่ได้ว่า F เรียน "แนวคิด joint-drift" หรือ "จำ generator"

การทดสอบ (holdout — ไม่เคยใช้ตอนออกแบบ/เลือกฟีเจอร์ของ F):
  A) UNSEEN campaign 5 family ที่จงใจหลบแกนของ F
       u_subsystem_shuffle  gap/duration ปกติ · subsystem แกว่งไปมา (ไม่ drift ทางเดียว)
       u_scope_only         gap ปกติ · เปลี่ยนเฉพาะ scope
       u_mixed_direction    gap "ช้าลง" (ตรงข้ามเดิม) + scope ขึ้น
       u_intermittent       สลับ phase ปกติ/ผิดปกติ (ไม่ monotonic)
       u_off_f_axis         แตะเฉพาะฟีเจอร์นอก F (concurrent/active_subsystem)
  B) campaign-like NORMAL — พฤติกรรมชอบธรรมที่ดูคล้าย campaign (ทดสอบ false positive)

ตัวชี้วัด: unique recall ของ F บน seen vs unseen (ถ้าตกเป็น ~0 = จำ pattern)
+ FPR บน campaign-like normal (ถ้าสูง = จับ "รูปทรง" ไม่ใช่ "ความผิดปกติ")

Run: cd hub/backend && SHARED_NAT=true PYTHONPATH=. python ../../ml-service/scripts/exp_overfit_check.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ML = Path(__file__).resolve().parent
sys.path.insert(0, str(ML))
import build_profiles_v2 as BP  # noqa: E402
import features_v2 as FE  # noqa: E402
import lc_l3_ownership as O  # noqa: E402
import lc_l3_sequence as SEQ  # noqa: E402
import lc_run_4layer as LC  # noqa: E402
from exp_l3_config_g import _fit_if, _score, _winfeat  # noqa: E402

from app.security.behavior_profiling import evaluate_behavior  # noqa: E402
from app.security.iforest_scorer import IForestResult  # noqa: E402
from app.security.risk_aggregator import aggregate  # noqa: E402
from app.security.rule_engine import evaluate_rules  # noqa: E402

REPORTS = LC.REPORTS
RANK = LC.RANK
SIZE = 5000
W = 5
NEUTRAL = IForestResult(0.0, 0.0, "neutral")
SEEN = "campaign"
UNSEEN = set(BP.UNSEEN_FAMILIES)


def gen_holdout(users_xlsx: Path):
    """generate ชุดเดิม + holdout (unseen campaign + campaign-like normal) ด้วย seed เดียวกัน."""
    import json

    users = LC.gen_all(users_xlsx)  # ชุดเดิม (train/val/test/attacks)
    roster = json.loads((BP.DATA / "roster_v2.json").read_text(encoding="utf-8"))
    ids = BP.load_identities(users_xlsx)
    rng = BP.random.Random(BP.SEED + 9001)  # stream แยก ไม่รบกวนชุดเดิม

    for spec in BP.SPEC:
        p = dict(spec)
        p["email"] = roster.get(p["alias"], "")
        p["rows"] = LC.POOL_ROWS
        ident = ids[p["email"]]
        u = users[p["alias"]]
        base = sorted(
            u["train_raw"] + [r for r, _ in u["test"]], key=lambda r: r["created_at"]
        )

        def feats(rows):
            out = []
            for r in sorted(rows, key=lambda r: r["created_at"]):
                t = r["created_at"]
                trusted = [x for x in base if x["created_at"] < t]
                out.append((r, FE.compute(r, trusted, trusted)))
            return out

        u["unseen"] = feats(BP.gen_unseen_campaigns(p, ident, rng))
        u["camp_like"] = feats(BP.gen_campaign_like_normal(p, ident, rng))
    return users


def run_seed(users):
    rows = []
    for alias, u in users.items():
        prof = LC.build_profile(u["train_raw"][:SIZE])
        tv, tr_ = u["train_ft"][:SIZE], u["train_raw"][:SIZE]
        base = O._baseline(tv)
        tres = [SEQ._resid(v, r, prof, base) for v, r in zip(tv, tr_)]
        model = _fit_if(
            [_winfeat(tres[i - W + 1 : i + 1]) for i in range(W - 1, len(tres))]
        )
        tail = tres[-(W - 1) :]

        def evaluate(pairs, label, group):
            if not pairs:
                return
            wins, run = [], list(tail)
            for raw, vec in pairs:
                r = SEQ._resid(vec, raw, prof, base)
                w = (run + [r])[-W:]
                while len(w) < W:
                    w = [w[0]] + w
                wins.append(_winfeat(w))
                run.append(r)
            _, fired, _ = _score(model, wins)
            for (raw, vec), f in zip(pairs, fired):
                rule = evaluate_rules(
                    vec, db=None, user_id=alias, ip=None, geo_country=None
                )
                beh = evaluate_behavior(
                    vec,
                    prof,
                    subsystem_id=raw.get("subsystem"),
                    user_agent=raw.get("user_agent"),
                )
                access = aggregate(rule, beh, NEUTRAL).decision
                rows.append(
                    dict(
                        label=label,
                        group=group,
                        scenario=raw.get("scenario", "normal"),
                        access=access,
                        fire=bool(f),
                    )
                )

        evaluate(u["test"], 0, "normal_test")
        evaluate(u.get("camp_like", []), 0, "campaign_like_normal")
        byscn = {}
        for raw, vec in u["attacks"]:
            byscn.setdefault(raw["scenario"], []).append((raw, vec))
        for scn, pairs in byscn.items():
            pairs.sort(key=lambda p: p[0]["created_at"])
            evaluate(pairs, 1, "campaign_seen" if scn == SEEN else "attack_other")
        by2 = {}
        for raw, vec in u.get("unseen", []):
            by2.setdefault(raw["scenario"], []).append((raw, vec))
        for scn, pairs in by2.items():
            pairs.sort(key=lambda p: p[0]["created_at"])
            evaluate(pairs, 1, f"unseen::{scn}")
    return rows


def metrics(rows):
    wn = lambda d: RANK[d] >= RANK["warn"]  # noqa: E731
    out = {}

    def grp(name):
        return [r for r in rows if r["group"] == name]

    def uniq(g):
        return (
            (sum(1 for r in g if r["fire"] and not wn(r["access"])) / len(g))
            if g
            else 0.0
        )

    def fpr(g):
        return (sum(r["fire"] for r in g) / len(g)) if g else 0.0

    out["seen_unique"] = uniq(grp("campaign_seen"))
    unseen_all = [r for r in rows if r["group"].startswith("unseen::")]
    out["unseen_unique"] = uniq(unseen_all)
    for fam in sorted(UNSEEN):
        out[f"fam::{fam}"] = uniq(grp(f"unseen::{fam}"))
    out["fpr_normal"] = fpr(grp("normal_test"))
    out["fpr_camp_like"] = fpr(grp("campaign_like_normal"))
    out["n_seen"] = len(grp("campaign_seen"))
    out["n_unseen"] = len(unseen_all)
    out["n_camp_like"] = len(grp("campaign_like_normal"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44, 45, 46])
    args = ap.parse_args()
    import time

    acc = []
    for seed in args.seeds:
        BP.SEED = seed
        t0 = time.time()
        acc.append(metrics(run_seed(gen_holdout(args.users))))
        print(f"seed {seed} done ({time.time() - t0:.0f}s)", flush=True)
    _print(acc, args.seeds)
    _report(acc, args.seeds)


def _ci(acc, key):
    return O.ci95([a[key] for a in acc])


def _print(acc, seeds):
    print("=" * 72)
    print(f"OVERFITTING CHECK ของ Config F ({len(seeds)} seeds)")
    print(
        f"  campaign seen {acc[0]['n_seen']} · unseen {acc[0]['n_unseen']} · "
        f"campaign-like normal {acc[0]['n_camp_like']}\n"
    )
    s, u = _ci(acc, "seen_unique"), _ci(acc, "unseen_unique")
    print(
        f"  {'unique recall (campaign SEEN)':38}{s[0] * 100:>7.1f}±{s[1] * 100:<5.1f}"
    )
    print(
        f"  {'unique recall (campaign UNSEEN)':38}{u[0] * 100:>7.1f}±{u[1] * 100:<5.1f}"
    )
    d = O.ci95([a["unseen_unique"] - a["seen_unique"] for a in acc])
    print(f"  {'ต่าง (unseen − seen)':38}{d[0] * 100:>+7.1f}±{d[1] * 100:<5.1f}\n")
    print("  แยกตาม family ที่ไม่เคยเห็น:")
    for fam in sorted(UNSEEN):
        m = _ci(acc, f"fam::{fam}")
        print(f"    {fam:24}{m[0] * 100:>7.1f}±{m[1] * 100:<5.1f}")
    fn, fc = _ci(acc, "fpr_normal"), _ci(acc, "fpr_camp_like")
    print(
        f"\n  L3 FPR: normal ปกติ {fn[0] * 100:.1f}±{fn[1] * 100:.1f}% · "
        f"campaign-like normal {fc[0] * 100:.1f}±{fc[1] * 100:.1f}%"
    )


def _report(acc, seeds):
    s, u = _ci(acc, "seen_unique"), _ci(acc, "unseen_unique")
    d = O.ci95([a["unseen_unique"] - a["seen_unique"] for a in acc])
    fn, fc = _ci(acc, "fpr_normal"), _ci(acc, "fpr_camp_like")
    generalize = u[0] > 0 and (u[0] - u[1]) > 0
    L = [
        "# ทดสอบ Overfitting ของ Config F — Unseen Campaign + Campaign-like Normal\n",
        "**วันที่:** 26 ส.ค. 2026  ",
        f"**seeds:** {seeds} (mean ± 95% CI) · size {SIZE} events/user  ",
        f"**ขนาด holdout:** campaign seen {acc[0]['n_seen']} · unseen {acc[0]['n_unseen']} · "
        f"campaign-like normal {acc[0]['n_camp_like']}\n",
        "\n## ข้อกังวลที่ทดสอบ\n",
        "campaign ชุดเดิม drift ใน `cadence`/`scope`/`subsystem_rarity` ซึ่งเป็น **แกนของ Config F พอดี**",
        "→ ผลเดิม (unique 16.3%) แยกไม่ออกว่า F เรียน *แนวคิด joint-drift* หรือ *จำ pattern ของ generator*\n",
        "\n## ผลหลัก\n",
        "| | unique recall |",
        "|---|---|",
        f"| campaign **SEEN** (ชุดที่ใช้พัฒนา) | {s[0] * 100:.1f} ± {s[1] * 100:.1f} |",
        f"| campaign **UNSEEN** (holdout, หลบแกน F) | **{u[0] * 100:.1f} ± {u[1] * 100:.1f}** |",
        f"| ต่าง (unseen − seen) | {d[0] * 100:+.1f} ± {d[1] * 100:.1f} |",
        "\n## แยกตาม family ที่ไม่เคยเห็น\n",
        "| family | สิ่งที่เปลี่ยนจาก campaign เดิม | unique recall |",
        "|---|---|---|",
    ]
    desc = {
        "u_subsystem_shuffle": "gap/duration ปกติ · subsystem แกว่งไปมา (ไม่ drift ทางเดียว)",
        "u_scope_only": "gap ปกติ · เปลี่ยนเฉพาะ scope",
        "u_mixed_direction": "gap **ช้าลง** (ตรงข้ามเดิม) + scope ขึ้น",
        "u_intermittent": "สลับ phase ปกติ/ผิดปกติ (ไม่ monotonic)",
        "u_off_f_axis": "แตะเฉพาะฟีเจอร์ **นอก** F (concurrent/active_subsystem)",
    }
    for fam in sorted(UNSEEN):
        m = _ci(acc, f"fam::{fam}")
        L.append(f"| `{fam}` | {desc[fam]} | {m[0] * 100:.1f} ± {m[1] * 100:.1f} |")
    L += [
        "\n## False positive — normal ที่ดูคล้าย campaign\n",
        "พฤติกรรมชอบธรรม: ทำงานถี่ขึ้น + ใช้เวลานานขึ้น + ขยับไป subsystem ที่ scope สูงขึ้น "
        "(เช่น ช่วงใกล้เดดไลน์)\n",
        "| ชุด | L3 FPR |",
        "|---|---|",
        f"| normal ปกติ | {fn[0] * 100:.1f} ± {fn[1] * 100:.1f}% |",
        f"| **campaign-like normal** | **{fc[0] * 100:.1f} ± {fc[1] * 100:.1f}%** |",
        "\n## ข้อสรุป\n",
        f"> **{'F generalize ได้ — จับ unseen campaign ที่หลบแกนตัวเองได้จริง' if generalize else 'F ไม่ generalize ไปยัง campaign รูปแบบใหม่ — ผลเดิมผูกกับ generator'}**\n",
    ]
    (REPORTS / "exp_overfit_check_2026-08-26.md").write_text(
        "\n".join(L), encoding="utf-8"
    )
    print("\nreport ->", REPORTS / "exp_overfit_check_2026-08-26.md")


if __name__ == "__main__":
    main()
