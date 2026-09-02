"""ตัวชี้วัดทั้งหมดของการทดลอง — นับอย่างเดียว ไม่มี logic การตัดสินใดๆ.

การตัดสินมาจาก `app.security.risk_fusion` เท่านั้น ไฟล์นี้รับผลมาแล้วนับ

**นิยามที่ต้องไม่กำกวม** (จุดที่การรายงานผิดพลาดได้ง่ายที่สุด):

    surfaced            ระบบหยิบเหตุการณ์ขึ้นมา = warn / challenge / block
    L3 raw unique       L3 ให้หลักฐานสูงกว่าเกณฑ์ แต่ชั้นอื่นไม่ให้
    L3 effective unique **เปลี่ยนผลจริง** — ถ้าไม่มี L3 จะปล่อยผ่าน แต่มี L3 แล้วถูกหยิบขึ้นมา
    L3 changed score    คะแนนต่าง แต่ผลการตัดสินเท่าเดิม -> **ห้ามนับเป็น effective**
    L3 overlap          ทั้ง L3 และชั้นอื่นต่างก็จับได้

ความต่างระหว่าง raw กับ effective คือหัวใจ — เคยวัดได้ 16.3% กับ 0.2% ในรอบก่อน
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

SURFACED = frozenset({"warn", "challenge", "block"})
BLOCKED = frozenset({"block"})
CHALLENGED = frozenset({"challenge", "block"})


def surfaced(decision: str) -> bool:
    return decision.removeprefix("would_") in SURFACED


@dataclass
class EventOutcome:
    """ผลของหนึ่งเหตุการณ์ภายใต้หนึ่ง config."""

    user: str
    is_attack: bool
    family: str | None
    campaign: str | None
    decision: str
    score: float
    # counterfactual — ผลถ้าไม่มีหลักฐาน L3 (ใช้ Policy Gate และ fusion ตัวเดียวกัน)
    decision_without_l3: str | None = None
    score_without_l3: float | None = None
    l3_evidence: float | None = None
    l3_abstained: bool = True
    other_layers_high: bool = False
    latency_ms: float | None = None

    @property
    def is_surfaced(self) -> bool:
        return surfaced(self.decision)

    @property
    def surfaced_without_l3(self) -> bool:
        return self.decision_without_l3 is not None and surfaced(
            self.decision_without_l3
        )

    @property
    def l3_changed_decision(self) -> bool:
        return (
            self.decision_without_l3 is not None
            and self.decision != self.decision_without_l3
        )

    @property
    def l3_changed_score_only(self) -> bool:
        return (
            not self.l3_changed_decision
            and self.score_without_l3 is not None
            and self.score != self.score_without_l3
        )

    @property
    def l3_effective_unique(self) -> bool:
        """เปลี่ยนผลจริงบน attack — ไม่นับกรณีคะแนนขยับแต่ยังปล่อยผ่านเหมือนเดิม."""
        return self.is_attack and not self.surfaced_without_l3 and self.is_surfaced


def _rate(k: int, n: int) -> float:
    return (k / n) if n else 0.0


@dataclass
class Summary:
    n_events: int = 0
    n_attack: int = 0
    n_normal: int = 0
    recall: float = 0.0
    precision: float = 0.0
    f1: float = 0.0
    warn_fpr: float = 0.0
    challenge_fpr: float = 0.0
    block_fpr: float = 0.0
    l3_raw_unique: float = 0.0
    l3_effective_unique: float = 0.0
    l3_changed_score_only: float = 0.0
    l3_overlap: float = 0.0
    l3_abstain_rate: float = 0.0
    mfa_per_1000_normal: float = 0.0
    latency_p50: float = 0.0
    latency_p95: float = 0.0
    per_family: dict = field(default_factory=dict)
    per_user_challenge_fpr: dict = field(default_factory=dict)


def summarize(rows: list[EventOutcome]) -> Summary:
    s = Summary()
    if not rows:
        return s
    atk = [r for r in rows if r.is_attack]
    nor = [r for r in rows if not r.is_attack]
    s.n_events, s.n_attack, s.n_normal = len(rows), len(atk), len(nor)

    tp = sum(1 for r in atk if r.is_surfaced)
    fp = sum(1 for r in nor if r.is_surfaced)
    s.recall = _rate(tp, len(atk))
    s.precision = _rate(tp, tp + fp)
    s.f1 = (
        2 * s.precision * s.recall / (s.precision + s.recall)
        if (s.precision + s.recall)
        else 0.0
    )

    s.warn_fpr = _rate(
        sum(1 for r in nor if r.decision.removeprefix("would_") == "warn"), len(nor)
    )
    s.challenge_fpr = _rate(
        sum(1 for r in nor if r.decision.removeprefix("would_") in CHALLENGED), len(nor)
    )
    s.block_fpr = _rate(
        sum(1 for r in nor if r.decision.removeprefix("would_") in BLOCKED), len(nor)
    )
    s.mfa_per_1000_normal = s.challenge_fpr * 1000

    # ── L3 ──
    with_cf = [r for r in rows if r.decision_without_l3 is not None]
    s.l3_abstain_rate = _rate(sum(1 for r in rows if r.l3_abstained), len(rows))
    if atk:
        s.l3_effective_unique = _rate(
            sum(1 for r in atk if r.l3_effective_unique), len(atk)
        )
        s.l3_raw_unique = _rate(
            sum(1 for r in atk if (r.l3_evidence or 0) > 0 and not r.other_layers_high),
            len(atk),
        )
        s.l3_overlap = _rate(
            sum(1 for r in atk if (r.l3_evidence or 0) > 0 and r.other_layers_high),
            len(atk),
        )
    if with_cf:
        s.l3_changed_score_only = _rate(
            sum(1 for r in with_cf if r.l3_changed_score_only), len(with_cf)
        )

    lat = sorted(r.latency_ms for r in rows if r.latency_ms is not None)
    if lat:
        s.latency_p50 = lat[len(lat) // 2]
        s.latency_p95 = lat[min(len(lat) - 1, int(len(lat) * 0.95))]

    # ── แยกตาม family ของการโจมตี ──
    fam: dict[str, list[EventOutcome]] = defaultdict(list)
    for r in atk:
        fam[r.family or "unknown"].append(r)
    s.per_family = {
        k: {"n": len(v), "recall": _rate(sum(1 for x in v if x.is_surfaced), len(v))}
        for k, v in sorted(fam.items())
    }

    # ── FPR รายผู้ใช้ — หาผู้ใช้ที่รับภาระผิดปกติ ──
    byu: dict[str, list[EventOutcome]] = defaultdict(list)
    for r in nor:
        byu[r.user].append(r)
    s.per_user_challenge_fpr = {
        u: _rate(
            sum(1 for x in v if x.decision.removeprefix("would_") in CHALLENGED), len(v)
        )
        for u, v in sorted(byu.items())
    }
    return s


def campaign_level(rows: list[EventOutcome]) -> dict:
    """นับระดับแคมเปญ — แคมเปญถือว่าถูกจับถ้ามีเหตุการณ์ใดเหตุการณ์หนึ่งถูกหยิบขึ้นมา.

    หน่วยนับนี้ตรงกับสิ่งที่ผู้ดูแลสนใจจริง (จับการโจมตีได้ไหม) มากกว่าการนับ
    รายเหตุการณ์ ซึ่งให้เครดิตกับการจับเหตุการณ์เดียวกันซ้ำๆ
    """
    camp: dict[str, list[EventOutcome]] = defaultdict(list)
    for r in rows:
        if r.is_attack and r.campaign:
            camp[r.campaign].append(r)
    if not camp:
        return {"n": 0, "surfaced": 0.0, "l3_only": 0.0}
    surfaced_n = sum(1 for v in camp.values() if any(x.is_surfaced for x in v))
    l3_only_n = sum(
        1
        for v in camp.values()
        if any(x.l3_effective_unique for x in v)
        and not any(x.surfaced_without_l3 for x in v)
    )
    return {
        "n": len(camp),
        "surfaced": _rate(surfaced_n, len(camp)),
        "l3_only": _rate(l3_only_n, len(camp)),
    }


def calibration_error(rows: list[EventOutcome], bins: int = 10) -> float:
    """Expected Calibration Error ของคะแนนความเสี่ยงเทียบอัตราการเป็น attack จริง."""
    if not rows:
        return 0.0
    buckets: dict[int, list[EventOutcome]] = defaultdict(list)
    for r in rows:
        buckets[min(bins - 1, int(r.score * bins))].append(r)
    total = len(rows)
    err = 0.0
    for b, v in buckets.items():
        conf = sum(x.score for x in v) / len(v)
        acc = sum(1 for x in v if x.is_attack) / len(v)
        err += (len(v) / total) * abs(conf - acc)
    return err


def score_only_ranking(rows: list[EventOutcome], target_fpr: float) -> dict:
    """⚠️ **การวิเคราะห์ ranking เท่านั้น — ไม่ใช่จุดทำงานที่ระบบทำได้จริง**.

    ตัดที่คะแนนดิบล้วน จึงข้าม Policy Gate · min_action · L3 solo cap ทั้งหมด
    ค่าที่ได้บอกได้แค่ว่า "คะแนนของ config นี้จัดอันดับ attack เหนือ normal ได้ดีแค่ไหน"
    ซึ่งเป็นคุณสมบัติของคะแนน ไม่ใช่ของระบบ

    **ห้ามใช้ตอบว่า "recall ที่ FPR 1%"** — ใช้ hybrid_experiment.sweep.search()
    ซึ่งเดินผ่าน resolver จริงแทน · ถ้า Policy Gate ทำให้ FPR ต่ำสุดเป็น 1.3%
    ตัวเลข ROC ที่ 1% คือจุดที่ระบบไปไม่ถึง

    เก็บไว้เพื่อรายงานเป็นการวิเคราะห์เสริม (เช่น เทียบ ranking ของ Config A
    ที่ใช้ threshold เดิม) โดยต้องติดป้ายกำกับให้ชัดทุกครั้ง
    """
    nor = sorted((r.score for r in rows if not r.is_attack), reverse=True)
    atk = [r.score for r in rows if r.is_attack]
    if not nor or not atk:
        return {
            "threshold": 1.0,
            "recall": 0.0,
            "actual_fpr": 0.0,
            "kind": "ranking_only",
        }
    k = int(target_fpr * len(nor))
    thr = nor[k] if k < len(nor) else nor[-1]
    return {
        "threshold": round(float(thr), 6),
        "recall": round(sum(1 for x in atk if x > thr) / len(atk), 4),
        "actual_fpr": round(sum(1 for x in nor if x > thr) / len(nor), 4),
        "kind": "ranking_only",
        "warning": "ไม่ผ่าน Policy Gate/resolver — ห้ามอ้างเป็นจุดทำงานจริง",
    }
