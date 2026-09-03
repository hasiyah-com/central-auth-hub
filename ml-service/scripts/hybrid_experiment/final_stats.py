"""ตัวเชื่อมสถิติ Round 2 เข้ากับ `cmd_final` — paired delta ระหว่าง config.

**ทำไมแยกโมดูล:** เพื่อ unit-test ได้โดยไม่ต้องเปิด final holdout · cmd_final เพียง
สร้าง event record (dict ต่อเหตุการณ์) แล้วเรียกฟังก์ชันในนี้ · ตรรกะการเทียบ
config อยู่ที่นี่ที่เดียว เทสตรึงคุณสมบัติได้ครบ

รูปแบบ event record ที่ทุกฟังก์ชันรับ (dict ต่อหนึ่งเหตุการณ์):

    {"user", "seed", "campaign", "is_attack", "surfaced", "challenged"}

`surfaced`  = decision อยู่ใน {warn, challenge, block}
`challenged`= decision อยู่ใน {challenge, block}

การเทียบทั้งหมดเป็น **paired** — candidate กับ config อื่นวัดบนเหตุการณ์ชุดเดียวกัน
ต่อรอบ bootstrap (บทเรียน Round 1: CI แบบ unpaired ที่ไม่ทับกันไม่ใช่การทดสอบ)
"""

from __future__ import annotations

from collections import defaultdict

from . import bootstrap as BS


def _tree_from_paired(cand: list[dict], other: list[dict]) -> dict:
    """จับคู่เหตุการณ์ candidate/other ตามลำดับ -> tree[user][seed] = [item].

    item เก็บบิตของทั้งสองแขนไว้ด้วยกัน เพื่อให้ stat วัดทั้งคู่บนชุดที่ resample
    เดียวกัน (นี่คือสิ่งที่ทำให้เป็น paired จริง)
    """
    if len(cand) != len(other):
        raise ValueError("cand กับ other ต้องยาวเท่ากันและเรียงตรงกันทุกเหตุการณ์")
    tree: dict = defaultdict(lambda: defaultdict(list))
    for c, o in zip(cand, other):
        item = {
            "is_attack": c["is_attack"],
            "campaign": c.get("campaign"),
            "cand_surf": c["surfaced"],
            "cand_ch": c["challenged"],
            "other_surf": o["surfaced"],
            "other_ch": o["challenged"],
        }
        tree[c["user"]][c["seed"]].append(item)
    return {u: dict(s) for u, s in tree.items()}


def _metric_pair(items: list[dict], metric: str) -> tuple[float, float]:
    """คำนวณ metric ของทั้งสองแขนบน items ชุดเดียวกัน."""
    if metric in ("recall", "recall_challenge"):
        atk = [x for x in items if x["is_attack"]]
        n = len(atk)
        if not n:
            return 0.0, 0.0
        if metric == "recall":
            return (
                sum(1 for x in atk if x["cand_surf"]) / n,
                sum(1 for x in atk if x["other_surf"]) / n,
            )
        return (
            sum(1 for x in atk if x["cand_ch"]) / n,
            sum(1 for x in atk if x["other_ch"]) / n,
        )
    if metric in ("challenge_fpr", "warn_or_worse_fpr"):
        nor = [x for x in items if not x["is_attack"]]
        n = len(nor)
        if not n:
            return 0.0, 0.0
        if metric == "challenge_fpr":
            return (
                sum(1 for x in nor if x["cand_ch"]) / n,
                sum(1 for x in nor if x["other_ch"]) / n,
            )
        return (
            sum(1 for x in nor if x["cand_surf"]) / n,
            sum(1 for x in nor if x["other_surf"]) / n,
        )
    raise ValueError(f"metric ไม่รู้จัก: {metric}")


def paired_config_delta(
    cand: list[dict],
    other: list[dict],
    *,
    metric: str,
    n_boot: int = 2000,
    seed: int = 0,
) -> dict:
    """Δmetric(candidate − other) แบบ paired hierarchical bootstrap.

    metric: recall | recall_challenge | challenge_fpr | warn_or_worse_fpr
    คืน delta, CI, sign_agreement (ทิศทางเสถียรแค่ไหนข้ามการสุ่มผู้ใช้)
    """
    tree = _tree_from_paired(cand, other)
    return BS.paired_hierarchical(
        tree,
        lambda items: _metric_pair(items, metric),
        n_boot=n_boot,
        seed=seed,
    )


def campaign_l3_only_tree(events: list[dict]) -> dict:
    """tree ระดับ **แคมเปญ** สำหรับ hierarchical_proportion — item = bool ต่อแคมเปญ.

    events แต่ละตัวต้องมี key `l3_only_hit` (แคมเปญนี้ถูกจับเฉพาะ L3 ที่เหตุการณ์นี้ไหม)
    แคมเปญถือว่า "L3-only" ถ้ามีเหตุการณ์ใดในแคมเปญเป็น l3_only_hit
    หน่วยนับคือแคมเปญ ไม่ใช่เหตุการณ์ (ตรงกับสิ่งที่ผู้ดูแลสนใจ)
    """
    by_camp: dict[tuple, bool] = defaultdict(bool)
    owner: dict[tuple, tuple] = {}
    for e in events:
        if not e.get("is_attack") or not e.get("campaign"):
            continue
        key = (e["user"], e["seed"], e["campaign"])
        by_camp[key] = by_camp[key] or bool(e.get("l3_only_hit"))
        owner[key] = (e["user"], e["seed"])
    tree: dict = defaultdict(lambda: defaultdict(list))
    for key, hit in by_camp.items():
        u, s = owner[key]
        tree[u][s].append(bool(hit))
    return {u: dict(sd) for u, sd in tree.items()}


def _campaign_caught(items: list[dict], arm: str) -> dict:
    """รวมเหตุการณ์เป็นแคมเปญ -> {campaign_key: caught?} สำหรับแขนที่ระบุ."""
    caught: dict = defaultdict(bool)
    surf_key = "cand_surf" if arm == "cand" else "other_surf"
    for x in items:
        if x["is_attack"] and x.get("campaign"):
            caught[x["campaign"]] = caught[x["campaign"]] or x[surf_key]
    return caught


def paired_campaign_recall_delta(
    cand: list[dict], other: list[dict], *, n_boot: int = 2000, seed: int = 0
) -> dict:
    """ΔCampaignRecall(candidate − other) — หน่วยคือแคมเปญ, paired.

    แคมเปญถือว่าจับได้ถ้ามีเหตุการณ์ใดถูก surface · วัดสัดส่วนแคมเปญที่จับได้
    ของทั้งสองแขนบนชุดเหตุการณ์ที่ resample เดียวกัน
    """
    tree = _tree_from_paired(cand, other)

    def stat(items: list[dict]) -> tuple[float, float]:
        cc = _campaign_caught(items, "cand")
        oc = _campaign_caught(items, "other")
        n = len(cc)
        if not n:
            return 0.0, 0.0
        return (
            sum(1 for v in cc.values() if v) / n,
            sum(1 for v in oc.values() if v) / n,
        )

    return BS.paired_hierarchical(tree, stat, n_boot=n_boot, seed=seed)


def paired_multi_delta(
    cand: list[dict], other: list[dict], *, n_boot: int = 2000, seed: int = 0
) -> dict:
    """ΔRecall, ΔRecall@ch, ΔChallengeFPR, ΔCampaignRecall — resample ครั้งเดียวต่อ boot.

    เทียบเท่าการเรียก paired_config_delta + paired_campaign_recall_delta แยกกัน แต่
    เร็วกว่าราว 4 เท่าเพราะ resample tree (แพงสุด) แค่รอบเดียวต่อ boot · ผลเป็น paired
    ทั้งภายในและข้าม metric (ทุก metric เห็นตัวอย่างชุดเดียวกัน)
    """
    tree = _tree_from_paired(cand, other)

    def multi(items: list[dict]) -> dict:
        # นับครั้งเดียว แยก attack/normal แล้วคำนวณทุก metric
        atk = [x for x in items if x["is_attack"]]
        nor = [x for x in items if not x["is_attack"]]
        na, nn = len(atk), len(nor)
        recall = (
            (sum(1 for x in atk if x["cand_surf"]) / na if na else 0.0),
            (sum(1 for x in atk if x["other_surf"]) / na if na else 0.0),
        )
        recall_ch = (
            (sum(1 for x in atk if x["cand_ch"]) / na if na else 0.0),
            (sum(1 for x in atk if x["other_ch"]) / na if na else 0.0),
        )
        ch_fpr = (
            (sum(1 for x in nor if x["cand_ch"]) / nn if nn else 0.0),
            (sum(1 for x in nor if x["other_ch"]) / nn if nn else 0.0),
        )
        cc = _campaign_caught(items, "cand")
        oc = _campaign_caught(items, "other")
        nc = len(cc)
        camp = (
            (sum(1 for v in cc.values() if v) / nc if nc else 0.0),
            (sum(1 for v in oc.values() if v) / nc if nc else 0.0),
        )
        return {
            "delta_recall": recall,
            "delta_recall_challenge": recall_ch,
            "delta_challenge_fpr": ch_fpr,
            "delta_campaign_recall": camp,
        }

    return BS.paired_hierarchical_multi(tree, multi, n_boot=n_boot, seed=seed)


def _aggregate_groups(cand: list[dict], other: list[dict]) -> tuple[dict, dict]:
    """สรุปสถิติพอเพียงต่อกลุ่ม (user, seed) — ทำครั้งเดียว ใช้ซ้ำทุก boot.

    การ bootstrap บนสถิติพอเพียงระดับกลุ่ม เร็วกว่าการ resample ทุกเหตุการณ์
    หลายร้อยเท่า (O(กลุ่ม) แทน O(เหตุการณ์) ต่อ boot) โดยให้ค่า point estimate
    เท่าเดิมเป๊ะ · แคมเปญ key ต่อกลุ่มจึงไม่ปนข้าม seed
    """
    if len(cand) != len(other):
        raise ValueError("cand กับ other ต้องยาวเท่ากันและเรียงตรงกัน")
    groups: dict[tuple, dict] = {}
    camp_tmp: dict[tuple, dict] = {}
    for c, o in zip(cand, other):
        gk = (c["user"], c["seed"])
        g = groups.get(gk)
        if g is None:
            g = groups[gk] = {
                "n_a": 0,
                "ca_surf": 0,
                "oa_surf": 0,
                "ca_ch": 0,
                "oa_ch": 0,
                "n_n": 0,
                "cn_ch": 0,
                "on_ch": 0,
            }
            camp_tmp[gk] = {}
        if c["is_attack"]:
            g["n_a"] += 1
            g["ca_surf"] += c["surfaced"]
            g["oa_surf"] += o["surfaced"]
            g["ca_ch"] += c["challenged"]
            g["oa_ch"] += o["challenged"]
            camp = c.get("campaign")
            if camp:
                cc = camp_tmp[gk].setdefault(camp, [False, False])
                cc[0] = cc[0] or c["surfaced"]
                cc[1] = cc[1] or o["surfaced"]
        else:
            g["n_n"] += 1
            g["cn_ch"] += c["challenged"]
            g["on_ch"] += o["challenged"]
    for gk, g in groups.items():
        g["camps"] = [tuple(v) for v in camp_tmp[gk].values()]
    # จัดกลุ่มตามผู้ใช้เพื่อ resample สองชั้น
    by_user: dict[str, list] = defaultdict(list)
    for (u, _s), g in groups.items():
        by_user[u].append(g)
    return groups, dict(by_user)


def _metrics_from_groups(chosen: list[dict]) -> dict:
    """รวมสถิติพอเพียงของกลุ่มที่ถูกเลือก -> (a, b) ต่อ metric."""
    n_a = ca_surf = oa_surf = ca_ch = oa_ch = 0
    n_n = cn_ch = on_ch = 0
    nc = c_caught = o_caught = 0
    for g in chosen:
        n_a += g["n_a"]
        ca_surf += g["ca_surf"]
        oa_surf += g["oa_surf"]
        ca_ch += g["ca_ch"]
        oa_ch += g["oa_ch"]
        n_n += g["n_n"]
        cn_ch += g["cn_ch"]
        on_ch += g["on_ch"]
        for cc, oc in g["camps"]:
            nc += 1
            c_caught += cc
            o_caught += oc
    r = lambda x, n: (x / n if n else 0.0)  # noqa: E731
    return {
        "delta_recall": (r(ca_surf, n_a), r(oa_surf, n_a)),
        "delta_recall_challenge": (r(ca_ch, n_a), r(oa_ch, n_a)),
        "delta_challenge_fpr": (r(cn_ch, n_n), r(on_ch, n_n)),
        "delta_campaign_recall": (r(c_caught, nc), r(o_caught, nc)),
    }


def paired_cluster_multi_delta(
    cand: list[dict],
    other: list[dict],
    *,
    n_boot: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> dict:
    """paired delta หลาย metric — bootstrap ระดับ cluster (user -> seed) บนสถิติพอเพียง.

    เป็น **2-level cluster bootstrap** (สุ่มผู้ใช้ แล้วสุ่ม seed ในผู้ใช้) บนสถิติที่
    สรุปต่อกลุ่มไว้ก่อน — เร็วพอสำหรับ 316k เหตุการณ์ · ต่างจาก paired_hierarchical
    (3-level) ตรงที่ไม่ resample เหตุการณ์ภายใน seed ซึ่งเป็นชั้นที่ความแปรปรวนน้อย
    ที่สุด · ความแปรปรวนหลักมาจากระดับผู้ใช้ซึ่งยังถูก resample เต็มที่

    point estimate (delta บนข้อมูลจริง) เท่ากับ paired_multi_delta เป๊ะ
    """
    import random as _random

    groups, by_user = _aggregate_groups(cand, other)
    all_groups = list(groups.values())
    if not all_groups:
        return {}
    base = _metrics_from_groups(all_groups)
    names = list(base)
    deltas0 = {k: base[k][0] - base[k][1] for k in names}
    users = list(by_user)
    rng = _random.Random(seed)
    dist: dict[str, list[float]] = {k: [] for k in names}
    for _ in range(n_boot):
        chosen: list[dict] = []
        for _ in range(len(users)):
            u = users[rng.randrange(len(users))]
            gs = by_user[u]
            chosen.extend(gs[rng.randrange(len(gs))] for _ in range(len(gs)))
        r = _metrics_from_groups(chosen)
        for k in names:
            dist[k].append(r[k][0] - r[k][1])
    out: dict = {}
    for k in names:
        d = deltas0[k]
        xs = sorted(dist[k])
        lo = xs[int((alpha / 2) * len(xs))]
        hi = xs[min(len(xs) - 1, int((1 - alpha / 2) * len(xs)))]
        if d > 0:
            agree = sum(1 for x in xs if x > 0) / len(xs)
        elif d < 0:
            agree = sum(1 for x in xs if x < 0) / len(xs)
        else:
            agree = sum(1 for x in xs if x == 0) / len(xs)
        out[k] = {
            "delta": round(d, 6),
            "ci_low": round(lo, 6),
            "ci_high": round(hi, 6),
            "sign_agreement": round(agree, 4),
            "n_boot_effective": len(xs),
            "method": "cluster_bootstrap_user_seed_2level",
        }
    return out
