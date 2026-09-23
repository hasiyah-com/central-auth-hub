"""Diagnostic — challenge FPR ของ normal block ต่างๆ ภายใน seed เดียวกัน.

ตอบคำถามเดียว: ถ้าเลือก threshold บน block ที่อยู่ "ไกลจาก calibration เท่ากับ
holdout" จะประมาณ FPR ของ holdout ได้ดีกว่า validation-tuning ปัจจุบันไหม

blocks (ต่อผู้ใช้ 1 คน, episode 50 event/ep):
  tune       ep 110-119  (validation ครึ่งหลัง — ที่ใช้อยู่ตอนนี้)
  testA      ep 120-129  (ครึ่งแรกของ test)
  testB      ep 130-139  (ครึ่งหลังของ test)
  test_even  ep 120,122,...,138
  test_odd   ep 121,123,...,139
  test_all   ep 120-139  (= holdout ปัจจุบัน)

ใช้เฉพาะ seed 42-46 ที่ holdout ถูกเปิดไปแล้ว (Round 1) — วินิจฉัยโครงสร้าง
ข้อมูล ไม่ใช่การเลือก threshold
"""

import sys
from dataclasses import replace
from pathlib import Path

ML = Path("E:/hub/central-auth-starter/ml-service")
sys.path.insert(0, str(ML / "scripts"))
sys.path.insert(0, str(Path("E:/hub/central-auth-starter/hub/backend")))

import exp_hybrid_gate as X  # noqa: E402
import gen_v3 as G3  # noqa: E402
from hybrid_experiment import configs as CFG  # noqa: E402
from hybrid_experiment import dataset as DS  # noqa: E402

import build_profiles_v2 as BP  # noqa: E402

USERS = BP.DEFAULT_USERS_XLSX
THR = {"warn": 0.98, "challenge": 0.995, "block": 0.9999}
GAMMA = 1.0
CHALLENGED = {"challenge", "block"}


def ep_filter(pairs, pred):
    return [(r, v) for r, v in pairs if pred(int(r["episode"]))]


def ch_fpr(rows):
    nor = [r for r in rows if not r.is_attack]
    if not nor:
        return 0.0, 0
    hit = sum(1 for r in nor if r.decision.removeprefix("would_") in CHALLENGED)
    return hit / len(nor), len(nor)


def run(seed, size, users_path):
    raw = G3.build_seed(users_path, seed)
    splits = DS.build(users_path, seed, size, raw=raw)
    point_model, seq_models, ecdf = X.fit_all(splits, size, raw)

    # ช่วง episode ของ test
    eps = sorted(
        {int(r["episode"]) for u in splits.values() for r, _ in u.holdout_normal}
    )
    lo, hi = eps[0], eps[-1]
    mid = lo + (hi - lo + 1) // 2
    blocks = {
        "testA": lambda e: e < mid,
        "testB": lambda e: e >= mid,
        "test_even": lambda e: (e - lo) % 2 == 0,
        "test_odd": lambda e: (e - lo) % 2 == 1,
        "test_all": lambda e: True,
    }

    out = {"_episodes": (lo, hi, mid)}

    ctxs = X.compute_layer_outputs(splits, point_model, seq_models, "tune")
    rows = X.apply_config(ctxs, CFG.CONFIGS["B"], ecdf, GAMMA, THR)
    out["tune"] = ch_fpr(rows)

    for name, pred in blocks.items():
        sub = {}
        for a, u in splits.items():
            sub[a] = replace(
                u,
                holdout_normal=ep_filter(u.holdout_normal, pred),
                holdout_attacks=[],
            )
        ctxs = X.compute_layer_outputs(sub, point_model, seq_models, "holdout")
        rows = X.apply_config(ctxs, CFG.CONFIGS["B"], ecdf, GAMMA, THR)
        out[name] = ch_fpr(rows)
    return out


if __name__ == "__main__":
    size = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    seeds = (
        [int(x) for x in sys.argv[2].split(",")]
        if len(sys.argv) > 2
        else [42, 43, 44, 45, 46]
    )
    names = ["tune", "testA", "testB", "test_even", "test_odd", "test_all"]
    print(f"DIAG split-distance · size={size} · challenge={THR['challenge']}")
    print(f"{'seed':>5} " + " ".join(f"{n:>10}" for n in names))
    acc = {n: [] for n in names}
    for s in seeds:
        r = run(s, size, USERS)
        print(f"{s:>5} " + " ".join(f"{r[n][0]*100:9.3f}%" for n in names), flush=True)
        for n in names:
            acc[n].append(r[n][0])
    print(
        f"{'mean':>5} "
        + " ".join(f"{sum(acc[n])/len(acc[n])*100:9.3f}%" for n in names)
    )
    print(f"{'max':>5} " + " ".join(f"{max(acc[n])*100:9.3f}%" for n in names))
    print(
        "\nn_normal ต่อ block (seed สุดท้าย): "
        + ", ".join(f"{n}={r[n][1]}" for n in names)
    )
