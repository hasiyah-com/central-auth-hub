"""รัน 4-Layer RBA บนชุดข้อมูล V2 + ประเมินผล.

มิเรอร์ production ทั้ง 4 ชั้น:
  L1 rule_engine.py       HARD_BLOCK_RULES + SCORE_RULES + multi_account_ip + cross_subsystem
  L2 behavior_profiling.py  hours_diff / weekend mismatch / cold start
  L3 iforest_scorer.py    IsolationForest + sigmoid(raw*5) + map_score (0/.1/.2/.4)
  L4 risk_aggregator.py   total = L1+L2+L3 (cap 1.0), block .85 / challenge .7 / warn .5

โปรโตคอล (one-class, ถูกต้อง):
  - แบ่งตามเวลาในแต่ละผู้ใช้: 80% แรก = train, 20% หลัง = test
  - TRAIN = normal เท่านั้น (ไม่เคยเห็น attack)
  - ATTACK = frozen ทั้งหมดอยู่ใน test
  - ให้คะแนนทุกแถวตามลำดับเวลา (cross-subsystem ต้องใช้ risk ของแถวก่อนหน้า)
    แต่วัดผลเฉพาะ test + attack

Run: py ml-service/scripts/run_4layer_v2.py
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, roc_auc_score

import contract_v2
from features_v2 import FEATURES

DATA = Path(__file__).resolve().parents[1] / "data"
TS = "%Y-%m-%d %H:%M:%S"
IDX = {f: i for i, f in enumerate(FEATURES)}

# ── ค่าคงที่ — คัดลอกจาก production ตรงตัว ──
HARD_BLOCK_RULES = [
    ("failed_logins_24h", 10),
    ("login_count_24h", 50),
    ("country_change_count_30d", 8),
]
SCORE_RULES = [
    ("is_new_device", "==", 1, 0.30),
    ("is_new_country", "==", 1, 0.30),
    ("is_new_user_agent_family", "==", 1, 0.20),
    ("failed_logins_24h", ">=", 3, 0.20),
    ("is_thailand", "==", 0, 0.10),
    ("impossible_travel_score", ">=", 0.5, 0.30),
]
MULTI_ACCOUNT_THRESHOLD, MULTI_ACCOUNT_SCORE, MULTI_ACCOUNT_WINDOW_SEC = 5, 0.25, 3600
CROSS_WINDOW_MIN, CROSS_THRESHOLD, CROSS_FACTOR = 30, 0.6, 0.3
MIN_SESSIONS, COLD_START_SCORE = 5, 0.20
THRESHOLDS = {"block": 0.85, "challenge": 0.7, "warn": 0.5}

# ขั้นต่ำที่ policy คาดหวังต่อ scenario (ตามรายงาน V2)
EXPECTED = {
    "combined_ato": "block",
    "new_os": "warn",
    "off_hours": "warn",
    "new_device": "challenge",
    "new_ua_family": "challenge",
    "failed_spike": "challenge",
    "login_velocity": "challenge",
    "concurrent_sessions": "challenge",
    "new_passkey": "challenge",
    "permission_change": "challenge",
    "subsystem_lateral": "challenge",
}
RANK = {"allow": 0, "warn": 1, "challenge": 2, "block": 3}


def parse(s: str) -> datetime:
    return datetime.strptime(s, TS)


# ══ Layer 1 ══════════════════════════════════════════════════════════════════
def layer1(
    f: list[float],
    now: datetime,
    subsystem: str,
    ip_timeline: list[tuple[datetime, str]],
    user_risk_hist: list[tuple[datetime, str, float]],
) -> tuple[bool, float, list[str]]:
    for name, thr in HARD_BLOCK_RULES:
        if f[IDX[name]] >= thr:
            return True, 1.0, [f"{name}={f[IDX[name]]:.0f} >= {thr} (hard block)"]

    score, reasons = 0.0, []
    for name, op, thr, w in SCORE_RULES:
        v = f[IDX[name]]
        if (op == ">=" and v >= thr) or (op == "==" and v == thr):
            score += w
            reasons.append(f"{name} (+{w})")

    # new_foreign_country — ไม่มีวันยิงในชุดนี้ (ไม่มี geo) แต่คงไว้ให้ตรง production
    if f[IDX["is_new_country"]] == 1 and f[IDX["is_thailand"]] == 0:
        score += 0.30
        reasons.append("new_foreign_country (+0.30)")

    # cross-subsystem risk propagation — ระบบ *อื่น* เพิ่งเสี่ยงสูงใน 30 นาที
    if subsystem != "HUB":
        cut = now - timedelta(minutes=CROSS_WINDOW_MIN)
        vals = [
            r
            for t, s, r in user_risk_hist
            if t >= cut and s != subsystem and s != "HUB"
        ]
        if vals and max(vals) >= CROSS_THRESHOLD:
            boost = round(max(vals) * CROSS_FACTOR, 2)
            score += boost
            reasons.append(f"cross_subsystem_risk {max(vals):.2f} (+{boost})")

    # multi-account จาก IP เดียวกัน — จุดตายของ campus NAT (ทุกคนใช้ IP เดียว)
    cut = now - timedelta(seconds=MULTI_ACCOUNT_WINDOW_SEC)
    n_users = len({u for t, u in ip_timeline if cut <= t < now})
    if n_users > MULTI_ACCOUNT_THRESHOLD:
        score += MULTI_ACCOUNT_SCORE
        reasons.append(f"multi_account_ip={n_users} (+{MULTI_ACCOUNT_SCORE})")

    return False, min(score, 1.0), reasons


# ══ Layer 2 ══════════════════════════════════════════════════════════════════
def build_profile(rows: list[dict]) -> dict | None:
    if len(rows) < MIN_SESSIONS:
        return None
    hours = [parse(r["created_at"]).hour for r in rows]
    wk = [1 if parse(r["created_at"]).weekday() >= 5 else 0 for r in rows]
    try:
        typical = statistics.mode(hours)
    except Exception:
        typical = 12
    return {"typical_hour": typical, "typical_weekend": round(sum(wk) / len(wk))}


def layer2(f: list[float], profile: dict | None) -> tuple[float, list[str]]:
    if profile is None:
        return COLD_START_SCORE, ["no_history (cold start)"]
    score, reasons = 0.0, []
    hd = f[IDX["hours_from_typical_login_time"]]
    if hd >= 10:
        score += 0.40
        reasons.append(f"hours_diff={hd:.1f} >= 10 (+0.40)")
    elif hd >= 6:
        score += 0.20
        reasons.append(f"hours_diff={hd:.1f} >= 6 (+0.20)")
    if f[IDX["is_new_country"]] == 1:
        score += 0.30
        reasons.append("is_new_country (+0.30)")
    cur_wk = 1 if f[IDX["day_of_week"]] >= 5 else 0
    if cur_wk != profile["typical_weekend"]:
        score += 0.10
        reasons.append("weekend_mismatch (+0.10)")
    return min(score, 1.0), reasons


# ══ Layer 3 ══════════════════════════════════════════════════════════════════
def map_score(raw: float) -> float:
    return 0.40 if raw >= 0.7 else 0.20 if raw >= 0.5 else 0.10 if raw >= 0.3 else 0.0


def sigmoid_score(model: IsolationForest, X: np.ndarray) -> np.ndarray:
    """เหมือน ml-service/app/model.py:predict_score."""
    raw = model.decision_function(X)
    return np.clip(1.0 / (1.0 + np.exp(raw * 5.0)), 0.0, 1.0)


# ══ Layer 4 ══════════════════════════════════════════════════════════════════
def decide(total: float) -> str:
    if total >= THRESHOLDS["block"]:
        return "block"
    if total >= THRESHOLDS["challenge"]:
        return "challenge"
    if total >= THRESHOLDS["warn"]:
        return "warn"
    return "allow"


# ══ metrics ══════════════════════════════════════════════════════════════════
def metrics(rows: list[dict]) -> dict:
    atk = [r for r in rows if r["label"] == 1]
    nor = [r for r in rows if r["label"] == 0]
    ch = lambda r: RANK[r["decision"]] >= RANK["challenge"]  # noqa: E731
    wn = lambda r: RANK[r["decision"]] >= RANK["warn"]  # noqa: E731
    tp = sum(1 for r in atk if ch(r))
    fp = sum(1 for r in nor if ch(r))
    recall = tp / len(atk) if atk else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    f1 = 2 * prec * recall / (prec + recall) if (prec + recall) else 0.0
    y = [r["label"] for r in rows]
    s = [r["total"] for r in rows]
    pol = sum(1 for r in atk if RANK[r["decision"]] >= RANK[EXPECTED[r["scenario"]]])
    return {
        "n_attack": len(atk),
        "n_normal": len(nor),
        "recall": recall,
        "precision": prec,
        "f1": f1,
        "challenge_fpr": fp / len(nor) if nor else 0.0,
        "warn_fpr": sum(1 for r in nor if wn(r)) / len(nor) if nor else 0.0,
        "policy_success": pol / len(atk) if atk else 0.0,
        "roc_auc": roc_auc_score(y, s) if len(set(y)) > 1 else float("nan"),
        "pr_auc": average_precision_score(y, s) if len(set(y)) > 1 else float("nan"),
    }


def run(
    condition: str, rows_all: list[dict], verbose: bool = True, mode: str = "production"
) -> tuple[dict, list[dict]]:
    """รัน 1 condition — คืน (metrics, scored rows ที่อยู่ใน test).

    mode = "production"  : กฎที่ใช้จริงตอนนี้ (rule_engine + behavior + iforest แบบบวกกัน)
    mode = "contract_v2" : ข้อเสนอตามรายงาน V2 (signal ownership + policy floor + NAT fix)
    """
    norm = sorted(
        [r for r in rows_all if r["label"] == 0 and r["normal_condition"] == condition],
        key=lambda r: r["created_at"],
    )
    atk = sorted(
        [r for r in rows_all if r["label"] == 1], key=lambda r: r["created_at"]
    )

    # ── split ตามเวลาในแต่ละผู้ใช้ 80/20 ──
    by_user = defaultdict(list)
    for r in norm:
        by_user[r["alias"]].append(r)
    train, test = [], []
    for rows in by_user.values():
        k = int(len(rows) * 0.8)
        train += rows[:k]
        test += rows[k:]

    # ── L3: เทรนบน normal-train เท่านั้น ──
    Xtr = np.array([[float(r[f]) for f in FEATURES] for r in train])
    model = IsolationForest(n_estimators=200, contamination=0.02, random_state=42).fit(
        Xtr
    )

    # ── L2: profile ของแต่ละคนจาก train (trusted history) ──
    profiles = {
        a: build_profile(by_user[a][: int(len(by_user[a]) * 0.8)]) for a in by_user
    }

    # ── ให้คะแนนตามลำดับเวลา (cross-subsystem ต้องใช้ค่าก่อนหน้า) ──
    train_set = {id(r) for r in train}
    ordered = sorted(train + test + atk, key=lambda r: r["created_at"])
    Xall = np.array([[float(r[f]) for f in FEATURES] for r in ordered])
    raws = sigmoid_score(model, Xall)

    ip_timeline: list[tuple[datetime, str]] = []
    user_risk: dict[str, list[tuple[datetime, str, float]]] = defaultdict(list)
    scored = []
    for r, raw in zip(ordered, raws):
        f = [float(r[x]) for x in FEATURES]
        now, sub, alias = parse(r["created_at"]), r["subsystem"], r["alias"]
        if mode.startswith("contract_v2"):
            cut = now - timedelta(seconds=MULTI_ACCOUNT_WINDOW_SEC)
            n_ip = len({u for t, u in ip_timeline if cut <= t < now})
            contract_v2.USE_NEW_SUBSYSTEM = mode == "contract_v2_plus"
            res = contract_v2.score(
                f,
                float(raw),
                map_score(float(raw)),
                n_ip,
                float(r.get("is_new_subsystem", 0.0)),
            )
            s1, s2, s3 = res["total"], 0.0, map_score(float(raw))
            total, dec, why1, why2 = res["total"], res["decision"], res["reasons"], []
        else:
            blocked, s1, why1 = layer1(f, now, sub, ip_timeline, user_risk[alias])
            if blocked:
                s2, s3, why2, total, dec = (
                    0.0,
                    0.0,
                    ["skipped (hard block)"],
                    1.0,
                    "block",
                )
            else:
                s2, why2 = layer2(f, profiles.get(alias))
                s3 = map_score(float(raw))
                total = min(round(s1 + s2 + s3, 4), 1.0)
                dec = decide(total)
        is_train = id(r) in train_set
        out = {
            **r,
            "rule": s1,
            "behavior": s2,
            "iforest": s3,
            "iforest_raw": float(raw),
            "total": total,
            "decision": dec,
            "reasons": "; ".join(why1 + why2),
            "split": "train" if is_train else "test",
            "mode": mode,
            "run_condition": condition,
            "evaluated": (not is_train) or r["label"] == 1,
        }
        scored.append(out)
        ip_timeline.append((now, alias))
        user_risk[alias].append((now, sub, total))

    evaluated = [r for r in scored if r["evaluated"]]
    m = metrics(evaluated)
    if verbose:
        print(
            f"\n{'='*72}\n[{mode}] condition = {condition}   "
            f"(train {len(train)} normal · test {len(test)} normal + {len(atk)} attack)"
        )
        print(
            f"  Challenge Recall {m['recall']:.1%} | Precision {m['precision']:.1%} | "
            f"F1 {m['f1']:.3f}"
        )
        print(
            f"  Challenge FPR {m['challenge_fpr']:.2%} | Warn FPR {m['warn_fpr']:.2%} | "
            f"Policy success {m['policy_success']:.1%}"
        )
        print(f"  ROC-AUC {m['roc_auc']:.3f} | PR-AUC {m['pr_auc']:.3f}")
    return m, evaluated, scored


def ablation(rows_all: list[dict], condition: str = "staggered") -> dict:
    """แต่ละชั้นทำอะไรได้เองบ้าง — เทียบกับ Full 4-Layer."""
    _, ev, _all = run(condition, rows_all, verbose=False)
    out = {}
    for name in ("Rule-only", "Behavior-only", "ML-only", "Full 4-Layer"):
        tmp = []
        for r in ev:
            if name == "Rule-only":
                t = r["rule"]
                d = "block" if r["rule"] >= 1.0 else decide(t)
            elif name == "Behavior-only":
                t = r["behavior"]
                d = decide(t)
            elif name == "ML-only":
                # native IForest boundary 0.5 (ตามรายงาน V2)
                t = r["iforest_raw"]
                d = "challenge" if t >= 0.5 else "allow"
            else:
                t, d = r["total"], r["decision"]
            tmp.append({**r, "total": t, "decision": d})
        out[name] = metrics(tmp)
    return out


def main() -> None:
    rows = list(csv.DictReader(open(DATA / "features_v2.csv", encoding="utf-8")))
    for r in rows:
        r["label"] = int(r["label"])

    results, all_eval, per_scenario, all_rows = {}, {}, {}, []
    for mode in ("production", "contract_v2", "contract_v2_plus"):
        for cond in ("staggered", "nat_burst"):
            m, ev, sc_all = run(cond, rows, mode=mode)
            results[f"{mode}/{cond}"] = m
            all_eval[(mode, cond)] = ev
            all_rows.extend(sc_all)

        # ── per-scenario ──
        ev = all_eval[(mode, "staggered")]
        print(f"\n  ผลรายชนิด attack [{mode}]")
        print(
            f"  {'scenario':22}{'n':>4}{'ขั้นต่ำ':>10}{'recall':>9}{'policy':>9}{'score':>9}"
        )
        per_sc = {}
        for sc in sorted(EXPECTED):
            g = [r for r in ev if r["scenario"] == sc]
            if not g:
                continue
            rec = sum(1 for r in g if RANK[r["decision"]] >= RANK["challenge"]) / len(g)
            pol = sum(1 for r in g if RANK[r["decision"]] >= RANK[EXPECTED[sc]]) / len(
                g
            )
            ms = statistics.mean(r["total"] for r in g)
            per_sc[sc] = {
                "n": len(g),
                "expected": EXPECTED[sc],
                "recall": rec,
                "policy": pol,
                "mean_score": ms,
            }
            print(
                f"  {sc:22}{len(g):>4}{EXPECTED[sc]:>10}{rec:>8.1%}{pol:>9.1%}{ms:>9.3f}"
            )
        per_scenario[mode] = per_sc

        print(f"\n  การตัดสินใจบน normal test [{mode}]")
        for cond in ("staggered", "nat_burst"):
            dist = Counter(
                r["decision"] for r in all_eval[(mode, cond)] if r["label"] == 0
            )
            n = sum(dist.values())
            print(
                f"    {cond:11} "
                + " ".join(
                    f"{k}={v} ({v/n:.1%})"
                    for k, v in sorted(dist.items(), key=lambda kv: RANK[kv[0]])
                )
            )

    # ── สรุปเทียบ 2 โหมด ──
    print(f"\n{'='*72}\nสรุปเทียบ (staggered)")
    print(
        f"{'mode':20}{'Recall':>9}{'Policy':>9}{'F1':>8}{'ChalFPR':>10}{'WarnFPR':>10}{'PR-AUC':>9}"
    )
    for mode in ("production", "contract_v2", "contract_v2_plus"):
        m = results[f"{mode}/staggered"]
        print(
            f"{mode:20}{m['recall']:>8.1%}{m['policy_success']:>9.1%}{m['f1']:>8.3f}"
            f"{m['challenge_fpr']:>9.2%}{m['warn_fpr']:>9.2%}{m['pr_auc']:>9.3f}"
        )

    # ── ablation (บน production) ──
    ab = ablation(rows)
    print(f"\n{'='*72}\nAblation — แต่ละชั้นช่วยอะไร (production, staggered)")
    print(
        f"{'layer':16}{'Recall':>9}{'Policy':>9}{'ChalFPR':>10}{'WarnFPR':>10}{'ROC':>8}{'PR':>8}"
    )
    for k, m in ab.items():
        print(
            f"{k:16}{m['recall']:>8.1%}{m['policy_success']:>9.1%}"
            f"{m['challenge_fpr']:>9.2%}{m['warn_fpr']:>9.2%}"
            f"{m['roc_auc']:>8.3f}{m['pr_auc']:>8.3f}"
        )

    # ── save ──
    with open(DATA / "results_v2.json", "w", encoding="utf-8") as f:
        json.dump(
            {"conditions": results, "per_scenario": per_scenario, "ablation": ab},
            f,
            ensure_ascii=False,
            indent=2,
        )
    cols = list(all_rows[0].keys())
    with open(DATA / "scored_v2.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_rows)
    print("\n✅ results_v2.json + scored_v2.csv")


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    main()
