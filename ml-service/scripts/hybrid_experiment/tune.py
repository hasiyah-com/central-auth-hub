"""Grid search — เก็บผลของชั้นไว้ในรูปที่ resolve ซ้ำได้ แล้วกวาด threshold.

**ทำไมต้องมีโมดูลนี้แยก:** การกวาด threshold ต้องเรียก resolver ของ production
ทุกจุด (บทเรียน B66 — harness ที่แปลงคะแนนเป็น action เองคือการวัดคนละระบบ)
แต่ถ้าเรียก `CFG.evaluate()` ใหม่ทุก threshold จะต้องคำนวณ L1/L2/L3 ซ้ำนับสิบล้านครั้ง

ทางออก: production แยก `ResolverInput` + `resolve_action()` ออกมาเป็น **จุดเดียว**
ที่แปลงคะแนนเป็น action · โมดูลนี้เก็บ `ResolverInput` ต่อเหตุการณ์ไว้ แล้วเรียก
`resolve_action()` ซ้ำที่ threshold ต่างๆ — ยังเป็นโค้ด production ตัวเดิม
ไม่มีสำเนา logic อยู่ในไฟล์นี้

หน่วยของการเลือกค่า: macro-average ข้าม (seed x size x user)
    ถ้า pool รวมกันหมด ผู้ใช้ที่มีเหตุการณ์เยอะและขนาดข้อมูลใหญ่จะครอบงำค่าที่เลือก
    ทำให้จุดทำงานที่ได้ดีกับบางกลุ่มแต่แย่กับที่เหลือ โดยตัวเลขรวมไม่ฟ้อง
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from app.security.risk_fusion import ResolverInput, resolve_action

from . import metrics as M


@dataclass
class EventRecord:
    """ผลของชั้นต่อหนึ่งเหตุการณ์ภายใต้ (config, gamma) หนึ่ง — resolve ซ้ำได้ทุก threshold."""

    user: str
    is_attack: bool
    family: str | None
    campaign: str | None
    resolver: ResolverInput | None = None
    resolver_no_l3: ResolverInput | None = None
    l3_evidence: float | None = None
    l3_abstained: bool = True
    max_other_evidence: float = 0.0
    latency_ms: float = 0.0
    # Config A (legacy aggregate) ตัดสินด้วย threshold ของตัวเองที่ตรึงไว้แล้ว
    # -> ไม่เข้าร่วมการกวาด threshold แต่ยังต้องรายงานเทียบได้
    fixed_decision: str | None = None
    fixed_score: float | None = None
    fixed_decision_no_l3: str | None = None
    fixed_score_no_l3: float | None = None


def resolve_rows(records: list[EventRecord], thresholds: dict) -> list[M.EventOutcome]:
    """แปลง record -> EventOutcome ที่ threshold ชุดหนึ่ง (เรียก resolver ของ production)."""
    out: list[M.EventOutcome] = []
    ch = thresholds["challenge"]
    for r in records:
        if r.fixed_decision is not None:
            dec, score = r.fixed_decision, r.fixed_score or 0.0
            dec0, score0 = r.fixed_decision_no_l3, r.fixed_score_no_l3
        else:
            dec = resolve_action(r.resolver, thresholds)[0]
            score = r.resolver.final_score
            if r.resolver_no_l3 is not None:
                dec0 = resolve_action(r.resolver_no_l3, thresholds)[0]
                score0 = r.resolver_no_l3.final_score
            else:
                dec0, score0 = None, None
        out.append(
            M.EventOutcome(
                user=r.user,
                is_attack=r.is_attack,
                family=r.family,
                campaign=r.campaign,
                decision=dec,
                score=score,
                decision_without_l3=dec0,
                score_without_l3=score0,
                l3_evidence=r.l3_evidence,
                l3_abstained=r.l3_abstained,
                other_layers_high=r.max_other_evidence >= ch,
                latency_ms=r.latency_ms,
            )
        )
    return out


def _mean(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


@dataclass
class CellStat:
    """สถิติของหนึ่ง (seed, size) — เก็บระดับผู้ใช้ไว้เพื่อ macro-average."""

    seed: int
    size: int
    per_user_recall: dict = field(default_factory=dict)
    # recall ที่นับเฉพาะ challenge/block — แยกจาก recall ที่รวม warn
    per_user_recall_challenge: dict = field(default_factory=dict)
    per_user_challenge_fpr: dict = field(default_factory=dict)
    per_user_block_fpr: dict = field(default_factory=dict)
    per_user_warn_fpr: dict = field(default_factory=dict)
    pooled: dict = field(default_factory=dict)
    l3_effective_unique: float = 0.0
    campaign: dict = field(default_factory=dict)


def cell_stat(seed: int, size: int, rows: list[M.EventOutcome]) -> CellStat:
    """สรุปหนึ่ง cell จาก EventOutcome — ใช้ตอนทำรายงานฉบับเต็ม (ไม่ใช่ในลูปค้นหา)."""
    by_user_atk: dict[str, list] = defaultdict(list)
    by_user_nor: dict[str, list] = defaultdict(list)
    for r in rows:
        (by_user_atk if r.is_attack else by_user_nor)[r.user].append(r)

    def frac(v, pred):
        return (sum(1 for x in v if pred(x)) / len(v)) if v else 0.0

    def act(x):
        return x.decision.removeprefix("would_")

    s = M.summarize(rows)
    return CellStat(
        seed=seed,
        size=size,
        per_user_recall={
            u: frac(v, lambda x: x.is_surfaced) for u, v in by_user_atk.items()
        },
        per_user_recall_challenge={
            u: frac(v, lambda x: act(x) in M.CHALLENGED) for u, v in by_user_atk.items()
        },
        per_user_challenge_fpr={
            u: frac(v, lambda x: act(x) in M.CHALLENGED) for u, v in by_user_nor.items()
        },
        per_user_block_fpr={
            u: frac(v, lambda x: act(x) in M.BLOCKED) for u, v in by_user_nor.items()
        },
        per_user_warn_fpr={
            u: frac(v, lambda x: act(x) == "warn") for u, v in by_user_nor.items()
        },
        pooled={
            "recall": s.recall,
            "recall_challenge": (
                sum(
                    1
                    for r in rows
                    if r.is_attack and r.decision.removeprefix("would_") in M.CHALLENGED
                )
                / max(1, sum(1 for r in rows if r.is_attack))
            ),
            "precision": s.precision,
            "f1": s.f1,
            "challenge_fpr": s.challenge_fpr,
            "block_fpr": s.block_fpr,
            "warn_fpr": s.warn_fpr,
            "n_attack": s.n_attack,
            "n_normal": s.n_normal,
        },
        l3_effective_unique=s.l3_effective_unique,
        campaign=M.campaign_level(rows),
    )


def stat_direct(
    records: list[EventRecord], seed: int, size: int, thresholds: dict
) -> CellStat:
    """เหมือน cell_stat แต่ไม่สร้าง EventOutcome ระหว่างทาง — ใช้ในลูปค้นหา.

    ลูปค้นหาเรียกฟังก์ชันนี้ราวห้าหมื่นครั้งต่อการทดลองหนึ่งรอบ การสร้าง
    dataclass กลางทางทำให้ใช้เวลาเป็นชั่วโมงโดยไม่ได้อะไรเพิ่ม · การตัดสิน
    ยังมาจาก `resolve_action()` ของ production เหมือนเดิมทุกแถว
    """
    atk_n: dict[str, int] = defaultdict(int)
    atk_hit: dict[str, int] = defaultdict(int)
    atk_hit_ch: dict[str, int] = defaultdict(int)
    nor_n: dict[str, int] = defaultdict(int)
    nor_warn: dict[str, int] = defaultdict(int)
    nor_ch: dict[str, int] = defaultdict(int)
    nor_blk: dict[str, int] = defaultdict(int)
    tp = fp = n_atk = n_nor = eff = tp_ch = 0
    camp_hit: dict[str, bool] = {}
    camp_hit_no_l3: dict[str, bool] = {}

    for r in records:
        if r.fixed_decision is not None:
            dec = r.fixed_decision.removeprefix("would_")
            dec0 = (r.fixed_decision_no_l3 or "").removeprefix("would_") or None
        else:
            dec = resolve_action(r.resolver, thresholds)[0]
            dec0 = (
                resolve_action(r.resolver_no_l3, thresholds)[0]
                if r.resolver_no_l3 is not None
                else None
            )
        surf = dec in M.SURFACED
        surf0 = dec0 in M.SURFACED if dec0 is not None else False
        if r.is_attack:
            n_atk += 1
            atk_n[r.user] += 1
            if dec in M.CHALLENGED:
                atk_hit_ch[r.user] += 1
                tp_ch += 1
            if surf:
                tp += 1
                atk_hit[r.user] += 1
                if not surf0:
                    eff += 1
            if r.campaign:
                camp_hit[r.campaign] = camp_hit.get(r.campaign, False) or surf
                camp_hit_no_l3[r.campaign] = (
                    camp_hit_no_l3.get(r.campaign, False) or surf0
                )
        else:
            n_nor += 1
            nor_n[r.user] += 1
            if surf:
                fp += 1
            if dec == "warn":
                nor_warn[r.user] += 1
            elif dec == "challenge":
                nor_ch[r.user] += 1
            elif dec == "block":
                nor_ch[r.user] += 1
                nor_blk[r.user] += 1

    recall = tp / n_atk if n_atk else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    n_camp = len(camp_hit)
    return CellStat(
        seed=seed,
        size=size,
        per_user_recall={u: atk_hit[u] / n for u, n in atk_n.items() if n},
        per_user_recall_challenge={u: atk_hit_ch[u] / n for u, n in atk_n.items() if n},
        per_user_challenge_fpr={u: nor_ch[u] / n for u, n in nor_n.items() if n},
        per_user_block_fpr={u: nor_blk[u] / n for u, n in nor_n.items() if n},
        per_user_warn_fpr={u: nor_warn[u] / n for u, n in nor_n.items() if n},
        pooled={
            "recall": recall,
            "recall_challenge": (tp_ch / n_atk) if n_atk else 0.0,
            "precision": precision,
            "f1": f1,
            "challenge_fpr": (sum(nor_ch.values()) / n_nor if n_nor else 0.0),
            "block_fpr": sum(nor_blk.values()) / n_nor if n_nor else 0.0,
            "warn_fpr": sum(nor_warn.values()) / n_nor if n_nor else 0.0,
            "n_attack": n_atk,
            "n_normal": n_nor,
        },
        l3_effective_unique=eff / n_atk if n_atk else 0.0,
        campaign={
            "n": n_camp,
            "surfaced": (
                sum(1 for v in camp_hit.values() if v) / n_camp if n_camp else 0.0
            ),
            "l3_only": (
                sum(
                    1
                    for k, v in camp_hit.items()
                    if v and not camp_hit_no_l3.get(k, False)
                )
                / n_camp
                if n_camp
                else 0.0
            ),
        },
    )


def macro(cells: list[CellStat]) -> dict:
    """macro-average ข้าม (seed x size x user) + แยกรายขนาดไว้ตรวจเงื่อนไข FPR.

    เงื่อนไข FPR ต้องผ่าน **ทุกขนาด** ไม่ใช่แค่ค่ารวม — จุดทำงานที่ FPR รวม 0.9%
    แต่ขนาด 50 อยู่ที่ 4% แปลว่าผู้ใช้ใหม่รับภาระเกินงบทั้งที่ตัวเลขรวมผ่าน
    """

    def cm(c: CellStat, name: str) -> float:
        return _mean(getattr(c, name).values())

    by_size: dict[int, list[CellStat]] = defaultdict(list)
    for c in cells:
        by_size[c.size].append(c)

    per_size = {}
    for size, cs in sorted(by_size.items()):
        per_size[size] = {
            "recall": _mean(cm(c, "per_user_recall") for c in cs),
            "recall_challenge": _mean(cm(c, "per_user_recall_challenge") for c in cs),
            "challenge_fpr": _mean(cm(c, "per_user_challenge_fpr") for c in cs),
            "block_fpr": _mean(cm(c, "per_user_block_fpr") for c in cs),
            "warn_fpr": _mean(cm(c, "per_user_warn_fpr") for c in cs),
            "pooled_challenge_fpr": _mean(c.pooled["challenge_fpr"] for c in cs),
            "pooled_recall": _mean(c.pooled["recall"] for c in cs),
            "l3_effective_unique": _mean(c.l3_effective_unique for c in cs),
            "n_cells": len(cs),
        }

    return {
        "recall": _mean(cm(c, "per_user_recall") for c in cells),
        "recall_challenge": _mean(cm(c, "per_user_recall_challenge") for c in cells),
        "challenge_fpr": _mean(cm(c, "per_user_challenge_fpr") for c in cells),
        "block_fpr": _mean(cm(c, "per_user_block_fpr") for c in cells),
        "warn_fpr": _mean(cm(c, "per_user_warn_fpr") for c in cells),
        "precision": _mean(c.pooled["precision"] for c in cells),
        "pooled_challenge_fpr": _mean(c.pooled["challenge_fpr"] for c in cells),
        "pooled_block_fpr": _mean(c.pooled["block_fpr"] for c in cells),
        "pooled_recall": _mean(c.pooled["recall"] for c in cells),
        "l3_effective_unique": _mean(c.l3_effective_unique for c in cells),
        "campaign_surfaced": _mean(c.campaign.get("surfaced", 0.0) for c in cells),
        "campaign_l3_only": _mean(c.campaign.get("l3_only", 0.0) for c in cells),
        "per_size": per_size,
        "n_cells": len(cells),
    }
