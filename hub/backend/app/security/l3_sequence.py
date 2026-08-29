"""Layer 3 (sequence channel) — per-user joint-residual anomaly เป็น "ธงเฝ้าระวัง".

ต่างจาก L3 เดิม (IForest 23 ฟีเจอร์ → บวก risk_score เข้า aggregate) สองเรื่อง:

  1. **feature ownership** — ใช้เฉพาะ residual รายคน 6 มิติ ที่ L1/L2 ไม่ได้ถือเป็นเจ้าของ
     (L1 ถือ deterministic flag · L2 ถือ rarity รายมิติ · L3 ถือ "ความผิดปกติร่วม")
  2. **surfacing channel ไม่ใช่การบวกคะแนน** — ยิงแล้วยก decision เป็น warn ตรงๆ
     (ห้ามแตะ challenge/block — ปล่อยให้ L1/L2 ตัดสิน friction)

เหตุผลของข้อ 2 (จาก tests/reports/l3_sequence_channel_2026-08-26.md):
  campaign ที่ L1/L2 พลาดมี base_total เฉลี่ยแค่ 0.23 → bonus +0.15 ดันถึง warn (0.5) ได้แค่ 2/71
  ทั้งที่ L3 จัดอันดับถูก (66% ของพวกนี้เกิน normal p95) → คอขวดคือวิธี integrate ไม่ใช่โมเดล
  เปลี่ยนเป็น channel: campaign surfaced 41.3% → 57.7% (+16.4pp), challenge FPR ไม่ขยับ (1.6%)

ทั้งหมด fail-safe ตาม B21 — ทุกฟังก์ชันคืนค่า "ไม่ยิง" เมื่อมีปัญหา ไม่ raise ขึ้นไปหา flow หลัก
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

from typing import Any

from app.security.rule_engine import FEAT
from app.services.l3_sequence_client import get_sequence_score

logger = logging.getLogger(__name__)

DIMS = 6  # [gap_log, scope, passkey_age_log, weekday_usage, hours_from_typical, sub_rarity]
# window sweep บน holdout (tests/reports/exp_l3_window_2026-08-26.md) ที่ FPR<=1%:
#   W=5  unique 1.3% @ FPR 0.6%   <- ดีที่สุด
#   W=10 unique 0.9% @ FPR 0.9%
#   W=5+10 (36 มิติ) แย่กว่าทั้งคู่ (signal dilution เหมือน Config G)
# ⚠️ เคยวัดได้ว่า W=10 ให้ 4.18% แต่เป็น artifact จาก window ที่คร่อมข้าม attack family
WINDOW = 5
MAX_HISTORY = 2000  # กันหน่วยความจำ/เวลา fit
# calibrate จาก threshold sweep บน holdout (tests/reports/exp_thr_and_gaps_2026-08-26.md):
#   p99=2.14% · p99.3=1.76% · p99.5=1.52% · p99.7=1.19% · **p99.9=0.79%** <- จุดเดียวที่ <=1%
# p99 บน validation ให้ FPR จริง 2.1% เพราะ test distribution ต่างจาก validation เล็กน้อย
CAL_FPR = 0.001  # anomaly: ยิง normal ~0.8% จริง (เป็น warn = ภาระ SOC ไม่ใช่ UX)
EXTREME_FPR = 0.0003  # extreme -> shadow would_challenge (ยังไม่ enforce)
REASON = "multivariate_behavioral_anomaly"
MODEL_VERSION = "iforest-l3-seq-v1"

# ── abstention tiers ตามจำนวน trusted history (แผน §5) ──
# ข้อมูล learning curve: 4.7% (50 events) -> 16.3% (5000) => ยิ่งมี history ยิ่งเชื่อได้
TIER_DIAGNOSTIC = 100  # 100-999: ให้คะแนน+log แต่ไม่เปลี่ยน decision
TIER_WARN = 1000  # 1000+: ยก warn ได้จริง
TIER_CHALLENGE = 2000  # 2000+: บันทึก would_challenge (shadow) เมื่อ extreme


def eligibility(n_history: int) -> str:
    """L3 ได้รับอนุญาตให้ทำอะไรบ้าง ตามปริมาณ history ของผู้ใช้คนนี้."""
    if n_history >= TIER_CHALLENGE:
        return "challenge"
    if n_history >= TIER_WARN:
        return "warn"
    if n_history >= TIER_DIAGNOSTIC:
        return "diagnostic"
    return "abstain"


# ── คำศัพท์ของแกน monitoring — ต้องไม่ทับกับ access decision vocab โดยเด็ดขาด ──
# access_decision     = L1/L2/L4 -> allow | challenge | block  (+ would_* ใน shadow mode)
# monitoring_decision = L3        -> normal | l3_investigate
MONITORING_NORMAL = "normal"
MONITORING_INVESTIGATE = "l3_investigate"


def _numeric():
    """โหลด numpy/sklearn แบบ lazy — hub-backend ไม่มี ML deps (แยกอยู่ ml-service)
    คืน None ถ้าไม่มี -> channel abstain เงียบๆ ไม่ทำ flow หลักพัง (B21)."""
    try:
        import numpy as np
        from sklearn.ensemble import IsolationForest

        return np, IsolationForest
    except ImportError:
        return None


@dataclass
class L3Result:
    fired: bool
    score: float
    reason: str | None = None
    tier: str = "none"  # none | anomaly | extreme
    raw_score: float = 0.0
    percentile: float = 0.0
    eligibility: str = "abstain"
    shadow_decision: str | None = (
        None  # would_warn / would_challenge (ไว้วิเคราะห์ ไม่ enforce)
    )
    # remote path ไม่มี L3Model ในมือ (โมเดลอยู่ที่ ml-service) จึงพก n_history มาเอง
    n_history: int = 0


@dataclass
class L3Model:
    forest: Any
    keep: Any
    threshold: float
    scale: float
    n_history: int
    extreme_threshold: float = 0.0
    dist: Any = None  # quantile grid ของ anomaly score บน train -> ใช้หา percentile
    base: list[tuple[float, float]] = field(
        default_factory=list
    )  # median/IQR ต่อมิติ ของคนนี้


def residual_raw(
    features: list[float], profile: dict | None, subsystem_id: str | None = None
) -> list[float] | None:
    """ดึง 6 ค่าดิบต่อเหตุการณ์ (ยังไม่ normalize — baseline คำนวณตอน fit จาก history ของคนนั้น).

    คืน None ถ้าไม่มี profile หรือ features ไม่ครบ (คนใหม่ → ไม่มีอะไรให้เทียบ)
    """
    try:
        if not profile or not features:
            return None
        total = profile.get("total") or profile.get("session_count") or 0
        sub_counts = profile.get("subsystem_counts") or {}
        # subsystem rarity (Laplace) — ตัวเดียวที่ต้องใช้ profile ตรงๆ
        sub_rarity = (
            1.0 - (sub_counts.get(subsystem_id, 0) + 1.0) / (total + 3.0)
            if total
            else 0.0
        )
        return [
            float(features[FEAT["log_minutes_since_last_login"]]),
            float(features[FEAT["scope_sensitivity_score"]]),
            math.log1p(max(float(features[FEAT["passkey_age_days"]]), 0.0)),
            float(features[FEAT["weekday_usage_score"]]),
            float(features[FEAT["hours_from_typical_login_time"]]),
            float(sub_rarity),
        ]
    except Exception as e:  # noqa: BLE001
        logger.warning("[l3_sequence] residual_raw error: %s", e)
        return None


def _center_scale(np, col) -> tuple[float, float]:
    med = float(np.median(col))
    iqr = float(np.quantile(col, 0.75) - np.quantile(col, 0.25))
    return med, max(iqr, 1e-6)


def _to_residual(np, raw, base: list[tuple[float, float]]):
    """z-score รายมิติ เทียบ median/IQR ของ 'คนนี้' (robust กว่า mean/std)."""
    out = np.empty_like(raw)
    for j, (med, scale) in enumerate(base):
        out[:, j] = (raw[:, j] - med) / scale
    return out


def _windows(np, res):
    """rolling window → 18 มิติ: [mean, slope(last-first), ptp] ต่อ residual dim.

    สิ่งที่จับได้คือ "รูปทรงของลำดับ" — campaign drift ทุกมิติพร้อมกันช้าๆ ซึ่ง
    การมองทีละเหตุการณ์ (point anomaly) มองไม่เห็น
    """
    n = len(res)
    if n < WINDOW:
        return np.empty((0, DIMS * 3))
    out = np.empty((n - WINDOW + 1, DIMS * 3))
    for i in range(WINDOW - 1, n):
        w = res[i - WINDOW + 1 : i + 1]
        out[i - WINDOW + 1] = np.concatenate(
            [w.mean(axis=0), w[-1] - w[0], w.max(axis=0) - w.min(axis=0)]
        )
    return out


def fit_user_model(
    history_raw: list[list[float]], n_history: int | None = None
) -> L3Model | None:
    """เทรน IForest รายคนบน window ของ history (normal ล้วน). คืน None = abstain."""
    try:
        if not history_raw or len(history_raw) < TIER_DIAGNOSTIC:
            return None
        num = _numeric()
        if num is None:
            return None  # ไม่มี ML deps ในเซอร์วิสนี้ -> abstain (ดู docstring ท้ายไฟล์)
        np, IsolationForest = num
        raw = np.asarray(history_raw[-MAX_HISTORY:], dtype=float)
        if raw.ndim != 2 or raw.shape[1] != DIMS or not np.isfinite(raw).all():
            return None
        base = [_center_scale(np, raw[:, j]) for j in range(DIMS)]
        X = _windows(np, _to_residual(np, raw, base))
        if len(X) < 20:
            return None
        keep = X.std(axis=0) > 1e-9
        if not keep.any():
            return None
        forest = IsolationForest(
            n_estimators=100, contamination=0.02, random_state=42
        ).fit(X[:, keep])
        a = -forest.score_samples(X[:, keep])
        thr = float(np.quantile(a, 1 - CAL_FPR))
        extreme = float(np.quantile(a, 1 - EXTREME_FPR))
        scale = float(max(np.quantile(a, 0.999) - thr, 1e-6))
        dist = np.quantile(
            a, np.linspace(0.0, 1.0, 101)
        )  # grid หา percentile ตอน score
        return L3Model(
            forest=forest,
            keep=keep,
            threshold=thr,
            scale=scale,
            n_history=n_history if n_history is not None else len(raw),
            base=base,
            extreme_threshold=extreme,
            dist=dist,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[l3_sequence] fit error: %s", e)
        return None


def evaluate_window(model: L3Model | None, window_raw: list[list[float]]) -> L3Result:
    """ให้คะแนน window ล่าสุด (ยาว WINDOW, เก่า→ใหม่). ยิงเมื่อเกิน threshold ที่ calibrate ไว้."""
    quiet = L3Result(fired=False, score=0.0)
    try:
        if model is None or not window_raw or len(window_raw) < WINDOW:
            return quiet
        num = _numeric()
        if num is None:
            return quiet
        np = num[0]
        raw = np.asarray(window_raw[-WINDOW:], dtype=float)
        if raw.shape != (WINDOW, DIMS) or not np.isfinite(raw).all():
            return quiet
        X = _windows(np, _to_residual(np, raw, model.base))
        if len(X) == 0:
            return quiet
        a = float(-model.forest.score_samples(X[:, model.keep])[0])
        elig = eligibility(model.n_history)
        pct = (
            float(np.searchsorted(model.dist, a) / 100.0)
            if model.dist is not None
            else 0.0
        )
        pct = min(max(pct, 0.0), 1.0)
        if a < model.threshold:
            return L3Result(
                fired=False, score=0.0, raw_score=a, percentile=pct, eligibility=elig
            )
        tier = "extreme" if a >= model.extreme_threshold else "anomaly"
        norm = float(np.clip((a - model.threshold) / model.scale, 0.0, 1.0))
        # shadow_decision = สิ่งที่ "จะทำ" ถ้าอนุญาตเต็มที่ (บันทึกไว้วิเคราะห์ ไม่ enforce)
        shadow = (
            "would_challenge"
            if (tier == "extreme" and elig == "challenge")
            else ("would_warn" if elig in ("warn", "challenge") else None)
        )
        return L3Result(
            fired=True,
            score=norm,
            reason=REASON,
            tier=tier,
            raw_score=a,
            percentile=pct,
            eligibility=elig,
            shadow_decision=shadow,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[l3_sequence] evaluate error: %s", e)
        return quiet


def monitoring_decision(result: L3Result) -> str:
    """ธงเฝ้าระวังของ L3 — **คนละแกนกับ access decision โดยสิ้นเชิง**.

        access_decision     = L1/L2/L4 -> allow | challenge | block   (ตัดสินสิทธิ์ผู้ใช้)
        monitoring_decision = L3        -> normal | l3_investigate    (ธงให้ SOC ดู)

    เดิมฟังก์ชันนี้คือ `apply_channel(decision, result)` ที่ยก access decision เป็น `warn`
    ซึ่งขัดกับข้อความที่รายงานว่า "L3 ไม่เปลี่ยน access decision" (warn อยู่ field เดียวกับ
    allow/challenge/block) — แยกเป็นสองแกนแทน การตรวจจับเหมือนเดิมทุกประการ
    เปลี่ยนแค่ว่าผลถูกบันทึกไว้ที่ field ไหน

    ไม่รับ access decision เข้ามาเป็นพารามิเตอร์เลย — ป้องกันการเผลอเอาไปแก้ค่านั้น
    """
    if not result.fired:
        return MONITORING_NORMAL
    # tier diagnostic/abstain: ให้คะแนน+log ได้ แต่ยังไม่น่าเชื่อพอจะรบกวน SOC (แผน §5)
    if result.eligibility not in ("warn", "challenge"):
        return MONITORING_NORMAL
    return MONITORING_INVESTIGATE


def to_contract(result: L3Result, model: L3Model | None) -> dict:
    """ผลของ L3 ต่อ login สำหรับ log/replay (แผน §9) — เก็บพอวิเคราะห์ ไม่เก็บ SHAP ทุกแถว."""
    return {
        # remote path ไม่มี model object ในมือ -> ยืนยันจาก n_history ที่ ml-service ส่งมา
        # (ถ้าเช็คแค่ `model is not None` จะได้ eligible=False เสมอ = ข้อมูล replay เพี้ยน)
        "eligible": bool(
            result.eligibility != "abstain"
            and (model is not None or result.n_history > 0)
        ),
        "eligibility": result.eligibility,
        "raw_score": round(result.raw_score, 4),
        "percentile": round(result.percentile, 4),
        # แกนของ L3 เท่านั้น — ไม่ใช่ access decision (ตั้งชื่อให้อ่านแล้วไม่สับสน)
        "monitoring_decision": monitoring_decision(result),
        # would_* = "ถ้าวันหนึ่งอนุญาตให้ enforce จะทำอะไร" — เก็บไว้วิเคราะห์เท่านั้น
        "shadow_decision": result.shadow_decision,
        "tier": result.tier,
        "score": round(result.score, 4),
        "model_version": MODEL_VERSION,
        # local path มี model object · remote path (ml-service) ส่ง n_history มากับ result
        "n_history": model.n_history if model else result.n_history,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Adapter — history ใน Redis + cache โมเดลรายคน (ส่วนที่แตะ I/O, fail-safe ทั้งหมด)
# ══════════════════════════════════════════════════════════════════════════════

_REDIS_KEY = "l3resid:{user_id}"
_CACHE_TTL_SEC = 3600  # refit อย่างมากชั่วโมงละครั้งต่อคน (fit ~50-150ms)
_MODEL_CACHE: dict[
    str, tuple[float, int, "L3Model | None"]
] = {}  # user -> (ts, n_hist, model)


def _load_history(redis, user_id: str) -> list[list[float]]:
    """ดึง residual ดิบล่าสุดของผู้ใช้จาก Redis (เก่า→ใหม่)."""
    import json

    raw = redis.lrange(_REDIS_KEY.format(user_id=user_id), -MAX_HISTORY, -1)
    out = []
    for item in raw:
        try:
            v = json.loads(item)
            if isinstance(v, list) and len(v) == DIMS:
                out.append([float(x) for x in v])
        except Exception:  # noqa: BLE001,S112
            continue
    return out


def record_residual(redis, user_id: str, resid: list[float] | None) -> None:
    """บันทึก residual ของ login ที่ผ่านแล้ว (เรียกหลังตัดสิน — เป็น history ของครั้งถัดไป)."""
    try:
        if not redis or not resid or len(resid) != DIMS:
            return
        import json

        key = _REDIS_KEY.format(user_id=user_id)
        pipe = redis.pipeline()
        pipe.rpush(key, json.dumps(resid))
        pipe.ltrim(key, -MAX_HISTORY, -1)
        pipe.execute()
    except Exception as e:  # noqa: BLE001
        logger.warning("[l3_sequence] record error: %s", e)


def _get_model(redis, user_id: str, history: list[list[float]]) -> L3Model | None:
    """โมเดลรายคนจาก cache — refit เมื่อหมดอายุ หรือ history โตขึ้นมาก (>10%)."""
    import time

    now = time.time()
    hit = _MODEL_CACHE.get(user_id)
    if hit and now - hit[0] < _CACHE_TTL_SEC and len(history) < hit[1] * 1.1:
        return hit[2]
    model = fit_user_model(history, n_history=len(history))
    _MODEL_CACHE[user_id] = (now, len(history), model)
    return model


def result_from_payload(payload: dict) -> L3Result:
    """แปลง payload จาก ml-service เป็น L3Result (ไม่ต้องใช้ numpy)."""
    fired = payload.get("fired") is True
    return L3Result(
        fired=fired,
        score=float(payload.get("score") or 0.0),
        reason=REASON if fired else None,
        tier=payload.get("tier") or "none",
        raw_score=float(payload.get("raw_score") or 0.0),
        percentile=float(payload.get("percentile") or 0.0),
        eligibility=payload.get("eligibility") or "abstain",
        shadow_decision=payload.get("shadow_decision"),
        n_history=int(payload.get("n_history") or 0),
    )


async def evaluate_login_remote(
    redis,
    user_id: str,
    features: list[float],
    profile: dict | None,
    subsystem_id: str | None = None,
):
    """เส้นทาง production — hub คำนวณ residual, ml-service ให้คะแนน.

    คืน (result, residual ของ login นี้) — ผู้เรียกส่ง residual เข้า record_residual()
    หลังตัดสินเสร็จ เพื่อเป็น history ของครั้งถัดไป (ไม่ปนเข้า window ที่กำลังตัดสิน)

    ทำไมไม่คำนวณเองที่ hub: image ไม่มี numpy/sklearn (แยก ML เป็น container ตั้งแต่ Week 5)
    -> `fit_user_model`/`evaluate_window` ในไฟล์นี้จะ abstain เงียบๆ เมื่อรันในคอนเทนเนอร์จริง
    เก็บไว้สำหรับการทดลอง/ทดสอบบนเครื่อง host ที่มี numpy (harness ใน ml-service/scripts)
    """
    try:
        resid = residual_raw(features, profile, subsystem_id)
        if resid is None:
            return L3Result(fired=False, score=0.0), None
        payload = await get_sequence_score(user_id, resid)
        if payload.get("error"):
            logger.warning("[l3_sequence] remote error: %s", payload["error"])
        return result_from_payload(payload), resid
    except Exception as e:  # noqa: BLE001
        logger.warning("[l3_sequence] evaluate_login_remote error: %s", e)
        return L3Result(fired=False, score=0.0), None


def evaluate_login(
    redis,
    user_id: str,
    features: list[float],
    profile: dict | None,
    subsystem_id: str | None = None,
):
    """ประเมิน login ปัจจุบันด้วย sequence channel.

    คืน (result, residual ของ login นี้, model) — ผู้เรียกควรส่ง residual เข้า
    record_residual() หลังตัดสินเสร็จ เพื่อเป็น history ของครั้งถัดไป
    (ไม่ปนเข้า window ที่กำลังตัดสิน) และใช้ model กับ to_contract() เพื่อ log
    """
    quiet = L3Result(fired=False, score=0.0)
    try:
        resid = residual_raw(features, profile, subsystem_id)
        if resid is None or not redis:
            return quiet, resid, None
        history = _load_history(redis, user_id)
        elig = eligibility(len(history))
        if elig == "abstain":
            return L3Result(fired=False, score=0.0, eligibility=elig), resid, None
        model = _get_model(redis, user_id, history)
        if model is None:
            return L3Result(fired=False, score=0.0, eligibility=elig), resid, None
        window = history[-(WINDOW - 1) :] + [resid]
        return evaluate_window(model, window), resid, model
    except Exception as e:  # noqa: BLE001
        logger.warning("[l3_sequence] evaluate_login error: %s", e)
        return quiet, None, None
