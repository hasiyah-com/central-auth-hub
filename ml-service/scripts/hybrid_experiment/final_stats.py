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
