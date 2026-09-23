"""ตรรกะของตัวสร้าง calibration artifact — แยกจาก CLI เพื่อให้ทดสอบได้ในคอนเทนเนอร์.

CLI ที่สร้างเหตุการณ์อยู่ที่ `ml-service/scripts/build_calibration.py` เพราะต้องใช้
numpy/sklearn ซึ่งมีเฉพาะใน ml-service (B61) · ไฟล์นี้ไม่ import ML dep เลย
จึงรันในคอนเทนเนอร์ hub-backend และในชุดเทสปกติได้

**สิ่งที่ไฟล์นี้ต้องรับผิดชอบ**

  1. สร้างกริดที่ `app/security/calibration.py` อ่านแล้วให้ค่าตามที่ตั้งใจ **เป๊ะ**
  2. แปลงเปอร์เซ็นไทล์ของคะแนนรวมเป็นเกณฑ์สัมบูรณ์ที่เอาไปใส่ `L4_THRESHOLD_*` ได้
  3. บอกว่าเกณฑ์ที่ประกาศไปถึงได้ด้วยอะไร และต้องพึ่ง "คะแนนชนะทุกตัวอย่าง" หรือไม่
  4. ตรวจว่าตารางเป็นตัวแทนของประชากรจริงหรือไม่ (หางเลื่อนไหม)

ข้อ 3 สำคัญเป็นพิเศษ: เกณฑ์ที่ประกาศว่า "เปอร์เซ็นไทล์ 0.9999" อาจกลายเป็น
"ชนะทุกตัวอย่างในตาราง" ถ้าตารางหยาบเกินไป — ความหมายต่างกันคนละเรื่อง และไม่มี
อะไรฟ้องถ้าไม่วัด (ตระกูลเดียวกับ B70 ที่ฟิลด์ประกาศว่าบังคับแต่ไม่เคยมีผล)
"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

LAYERS = ("rule", "behavior", "anomaly_point", "anomaly_sequence")
DEFAULT_GRID_N = 20000
DEFAULT_LEVELS = {"p95": 0.95, "p99": 0.99, "p999": 0.999}


class InsufficientSamples(Exception):
    """ขอเปอร์เซ็นไทล์ที่ข้อมูลไม่มีหางพอจะตอบ — ต้องบอก ไม่ใช่คืนค่ามั่ว."""


# ══════════════════════════════════════════════════════════════════════════════
# กริดควอนไทล์ — ต้องเข้ากันได้กับ app/security/calibration.py:cdf()
# ══════════════════════════════════════════════════════════════════════════════


def quantile_grid(samples, n: int = DEFAULT_GRID_N) -> list[float]:
    """คะแนน login ปกติ -> กริดเรียงจากน้อยไปมากยาว min(n, จำนวนตัวอย่าง).

    เลือก order statistic ที่ระยะห่างเท่ากัน `s[floor(i*N/n)]` เพื่อให้
    `bisect_left(grid, x) / len(grid)` ประมาณ "สัดส่วนของตัวอย่างที่น้อยกว่า x
    อย่างเคร่งครัด" ซึ่งเป็นนิยามเดียวกับที่ `calibration.cdf()` ใช้

    ค่าซ้ำถูกเก็บไว้ตามสัดส่วนโดยอัตโนมัติ — ถ้า 85% ของตัวอย่างเป็น 0.0
    กริด 85% แรกก็เป็น 0.0 ทำให้ 0.0 ได้หลักฐาน 0.0 ตามที่ควรเป็น
    """
    s = sorted(float(x) for x in samples)
    total = len(s)
    if total == 0:
        return []
    if total <= n:
        return s
    return [s[(i * total) // n] for i in range(n)]


def evidence_of(grid, raw: float) -> float:
    """จำลอง `calibration.cdf()` เพื่อใช้ตรวจ — ต้องให้ค่าเท่ากันเป๊ะ.

    คะแนนที่ชนะทุกค่าในตารางได้ 1.0 (ไม่ใช่ (n-1)/n) เพราะ `bisect_left`
    คืน `len(grid)` — เพดานจึงเป็น 1.0 แต่ **ช่องว่าง** ระหว่างค่าที่เป็นไปได้
    ถัดลงมากับ 1.0 คือสิ่งที่ทำให้เกณฑ์สูง ๆ เปลี่ยนความหมาย ดู `reachability()`
    """
    if not grid:
        return 0.0
    return bisect.bisect_left(grid, float(raw)) / len(grid)


def tie_mass(samples, value: float = 0.0) -> float:
    """สัดส่วนของตัวอย่างที่เท่ากับค่านี้พอดี.

    L1/L2 เป็นผลรวมน้ำหนักของกฎไม่กี่ตัว ค่าจึงไม่ต่อเนื่อง — มวลที่ 0.0 บอกว่า
    "กฎเดียวที่ยิง" จะกระโดดไปได้หลักฐานเท่าไรทันที ซึ่งกำหนดว่าเกณฑ์ warn
    แยกอะไรได้จริงหรือไม่
    """
    s = [float(x) for x in samples]
    if not s:
        return 0.0
    return sum(1 for x in s if x == value) / len(s)


# ══════════════════════════════════════════════════════════════════════════════
# เปอร์เซ็นไทล์ของคะแนนรวม -> เกณฑ์สัมบูรณ์
# ══════════════════════════════════════════════════════════════════════════════


def _nearest_rank(sorted_vals: list[float], p: float) -> float:
    """นิยามเดียวกับ `hybrid_experiment/tailcal.py:_quantile` — ห้ามต่างกัน."""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    return sorted_vals[min(int(p * n), n - 1)]


def tail_counts(final_scores, percentiles: dict) -> dict:
    """จำนวนตัวอย่างที่อยู่เหนือแต่ละเปอร์เซ็นไทล์ — ตัวชี้ว่าเชื่อหางได้แค่ไหน."""
    n = len(final_scores)
    return {name: n * (1.0 - p) for name, p in percentiles.items()}


def derive_thresholds(
    final_scores, percentiles: dict, min_tail_count: float = 1.0
) -> dict:
    """เปอร์เซ็นไทล์ของคะแนน **รวม** -> ค่าที่เอาไปใส่ `L4_THRESHOLD_*`.

    ต้องมาจาก distribution ของคะแนนรวม ไม่ใช่ของชั้นใดชั้นหนึ่ง — เกณฑ์ของ
    Config B ถูกหามาแบบนี้ตั้งแต่ต้น (`hybrid_experiment/sweep.py`) และเกณฑ์กับ
    ตาราง calibration ผูกกัน เปลี่ยนตารางแล้วเกณฑ์เดิมใช้ไม่ได้
    """
    s = sorted(float(x) for x in final_scores)
    counts = tail_counts(s, percentiles)
    # เผื่อความคลาดเคลื่อนของทศนิยม — 10000 * (1 - 0.9999) ได้ 0.9999999999998
    # ซึ่งควรนับเป็น 1 ไม่ใช่ "ไม่ถึง 1"
    thin = {k: v for k, v in counts.items() if v + 1e-9 < min_tail_count}
    if thin:
        raise InsufficientSamples(
            "ตัวอย่างไม่พอจะตอบเปอร์เซ็นไทล์นี้: "
            + ", ".join(f"{k} เหลือหางแค่ {v:.2f} ตัวอย่าง" for k, v in thin.items())
        )
    return {name: _budget_threshold(s, 1.0 - p) for name, p in percentiles.items()}


def fire_rate(scores, threshold: float) -> float:
    """สัดส่วนที่ยิง — นิยามเดียวกับ `risk_fusion._action_for` ซึ่งเทียบด้วย `>=`."""
    vals = [float(x) for x in scores]
    if not vals:
        return 0.0
    return sum(1 for x in vals if x >= threshold) / len(vals)


def _budget_threshold(sorted_vals: list[float], budget: float) -> float:
    """เกณฑ์ที่ต่ำที่สุดซึ่ง `P(score >= t)` ไม่เกินงบ.

    ห้ามใช้ nearest-rank ตรง ๆ — คะแนนของ L1+L2 มีค่าซ้ำเป็นกลุ่มใหญ่ ถ้าเกณฑ์ตก
    กลางกลุ่ม production ที่เทียบด้วย `>=` จะกวาดทั้งกลุ่มเข้าไปแล้วยิงเกินงบ
    (วัดได้จริงบน P48-T2: warn ยิง 2.85% จากงบ 2%) จึงเลือกค่าที่ไม่ซ้ำตัวแรก
    ที่ยังอยู่ในงบ และถ้าแม้ค่าสูงสุดก็เกินงบ ให้เกณฑ์อยู่เหนือทุกค่าที่เคยเห็น
    """
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    tol = 1e-12
    prev = None
    for i, v in enumerate(sorted_vals):
        if v == prev:
            continue
        prev = v
        # bisect_left ของค่าซ้ำตัวแรก = i พอดี เพราะวนจากน้อยไปมาก
        if (n - i) / n <= budget + tol:
            return v
    return math.nextafter(sorted_vals[-1], math.inf)


# ══════════════════════════════════════════════════════════════════════════════
# reachability — เกณฑ์ที่ประกาศ ระบบไปถึงได้ด้วยอะไร
# ══════════════════════════════════════════════════════════════════════════════


def _fuse(m: float, s: float, gamma: float) -> float:
    """สูตรเดียวกับ `risk_fusion.fuse` — max + corroboration."""
    return m + gamma * s * (1.0 - m)


def _attainable_evidence(grids: dict) -> list[float]:
    """ค่า evidence ที่เป็นไปได้ทั้งหมด = rank/n ของแต่ละตาราง (รวม 1.0)."""
    values = set()
    for grid in grids.values():
        n = len(grid)
        if n:
            values.update(i / n for i in range(n + 1))
    return sorted(values)


def _anomaly_alone_capped(threshold_block: float, thresholds: dict) -> bool:
    """ถาม **ตัวตัดสินจริง** ว่า L3 เดี่ยวที่คะแนนเต็มยัง block ไม่ได้ใช่ไหม.

    ไม่เขียนกติกาซ้ำที่นี่ — เรียก `resolve_action` ของ production ตรง ๆ
    เพราะกติกาที่คัดลอกมาไว้เองคือที่มาของ B66
    """
    from app.security.risk_fusion import ResolverInput, resolve_action

    action, capped = resolve_action(
        ResolverInput(
            final_score=1.0,
            policy_denied=False,
            policy_min_action=None,
            primary_layer="anomaly",
            other_evidence=(),
        ),
        thresholds,
    )
    return action != "block" and capped


def reachability(grids: dict, gamma: float, thresholds: dict) -> dict:
    """เกณฑ์แต่ละระดับไปถึงได้ไหม ด้วยคู่หลักฐานแบบใด และมีช่องว่างแค่ไหน.

    รายงานต่อเกณฑ์
        reachable                           มีคู่ (m, s) ที่ทำให้คะแนนรวมถึงเกณฑ์
        highest_below_threshold             คะแนนรวมสูงสุดที่ยัง **ไม่** ถึงเกณฑ์
        min_pair                            คู่ที่ต่ำที่สุดที่ถึงเกณฑ์
        single_layer_needs_exceeding_table  ชั้นเดียวจะถึงเกณฑ์ได้ต้องชนะทุกตัวอย่าง
        anomaly_alone_capped                L3 เดี่ยวถูกกดไม่ให้ block (เฉพาะ block)
    """
    values = _attainable_evidence(grids)
    out: dict = {}
    for name, thr in thresholds.items():
        best_below = 0.0
        min_pair = None
        for m in values:
            for s in (0.0, m):
                final = _fuse(m, s, gamma)
                if final >= thr:
                    if min_pair is None or final < _fuse(*min_pair, gamma):
                        min_pair = (m, s)
                elif final > best_below:
                    best_below = final
        # ชั้นเดียว (s = 0) -> คะแนนรวมเท่ากับ m พอดี
        below_one = [v for v in values if v < 1.0]
        single_alone = max(below_one) if below_one else 0.0
        entry = {
            "reachable": min_pair is not None,
            "highest_below_threshold": round(best_below, 9),
            "min_pair": (
                {"m": round(min_pair[0], 9), "s": round(min_pair[1], 9)}
                if min_pair
                else None
            ),
            "single_layer_needs_exceeding_table": single_alone < thr,
        }
        if name == "block":
            entry["anomaly_alone_capped"] = _anomaly_alone_capped(thr, thresholds)
        out[name] = entry
    return out


# ══════════════════════════════════════════════════════════════════════════════
# ตรวจคุณภาพตาราง — หางเลื่อนไหม
# ══════════════════════════════════════════════════════════════════════════════


def exceedance(fit, check, levels: dict | None = None) -> dict:
    """ตั้งเกณฑ์ที่เปอร์เซ็นไทล์ของ `fit` แล้ววัดว่า `check` เกินกี่สัดส่วน.

    ถ้าสองชุดมาจาก distribution เดียวกัน ค่าต้องใกล้ `1 - p` · ถ้าสูงกว่าชัดเจน
    แปลว่าหางของประชากรจริงหนักกว่าที่ตารางเห็น ซึ่งคือกลไกที่ทำให้ FPR บน
    holdout สูงกว่าที่จูนไว้บน validation

    นิยามตรงกับ `hybrid_experiment/tailcal.py:benign_exceedance` (มีเทส parity
    บน host) — ตรรกะเดียวกันอยู่สองที่เพราะคอนเทนเนอร์คนละตัวเห็นโค้ดคนละชุด
    """
    lv = levels or DEFAULT_LEVELS
    q = sorted(float(x) for x in fit)
    ev = [float(x) for x in check]
    if not ev:
        return {name: 0.0 for name in lv}
    out = {}
    for name, p in lv.items():
        thr = _nearest_rank(q, p)
        out[name] = sum(1 for x in ev if x > thr) / len(ev)
    return out


def pit_ks(fit, check) -> float:
    """KS ของ PIT เทียบกับ uniform — 0 แปลว่าสองชุดมาจาก distribution เดียวกัน.

    PIT ใช้ `bisect_right` (สัดส่วนที่ **ไม่เกิน**) ตามนิยามของ tailcal
    ซึ่งต่างจาก `calibration.cdf` ที่ใช้ `bisect_left` โดยตั้งใจ — คนละคำถาม
    """
    q = sorted(float(x) for x in fit)
    n = len(q)
    if n == 0 or not len(check):
        return 0.0
    pit = sorted(bisect.bisect_right(q, float(x)) / n for x in check)
    m = len(pit)
    d = 0.0
    for i, p in enumerate(pit):
        d = max(d, abs((i + 1) / m - p), abs(p - i / m))
    return d


# ══════════════════════════════════════════════════════════════════════════════
# ประกอบไฟล์ + ตรวจก่อนใช้
# ══════════════════════════════════════════════════════════════════════════════


def build_artifact(
    *,
    version: str,
    grids: dict,
    final_scores,
    percentiles: dict,
    gamma: float,
    source: dict,
    normal_definition: str,
    population: dict | None = None,
    raw_samples: dict | None = None,
    check_final_scores=None,
    check_layer_samples: dict | None = None,
    created_from: str = "validation-calibration",
    min_tail_count: float = 1.0,
    fusion_config: str = "B",
) -> dict:
    """ประกอบทุกอย่างที่ตัดสินใจได้จากรันเดียว ไว้ในไฟล์เดียว.

    ตาราง calibration กับเกณฑ์ต้องอยู่ด้วยกันเสมอ เพราะเปลี่ยนตารางแล้ว
    distribution ของคะแนนรวมเลื่อน เกณฑ์เดิมจึงใช้ไม่ได้ — แยกไฟล์เมื่อไร
    จะมีวันที่สองอย่างไม่ตรงกันโดยไม่มีใครรู้
    """
    finals = sorted(float(x) for x in final_scores)
    thresholds = derive_thresholds(finals, percentiles, min_tail_count=min_tail_count)
    samples = raw_samples or {}

    checks: dict = {
        "tail_counts": {
            k: round(v, 3) for k, v in tail_counts(finals, percentiles).items()
        },
        # อัตรายิงจริงด้วยนิยามของ production (>=) — exceedance ด้านล่างใช้ > ตาม tailcal
        # สองนิยามต่างกันมากเมื่อคะแนนมีค่าซ้ำ จึงต้องรายงานทั้งคู่
        "fire_rate_fit": {
            k: round(fire_rate(finals, t), 6) for k, t in thresholds.items()
        },
    }
    if check_final_scores:
        checks["fire_rate_check"] = {
            k: round(fire_rate(check_final_scores, t), 6) for k, t in thresholds.items()
        }
    if check_final_scores:
        checks["final_exceedance"] = {
            k: round(v, 6) for k, v in exceedance(finals, check_final_scores).items()
        }
        checks["final_pit_ks"] = round(pit_ks(finals, check_final_scores), 6)
    if check_layer_samples:
        checks["layer_exceedance"] = {
            layer: {k: round(v, 6) for k, v in exceedance(grids[layer], vals).items()}
            for layer, vals in check_layer_samples.items()
            if layer in grids
        }
    if "final_exceedance" not in checks:
        checks["note"] = "ยังไม่ได้ตรวจหางด้วยชุดที่สอง — ห้ามใช้ตารางนี้ตั้งเกณฑ์จริง"

    return {
        "version": version,
        "created_from": created_from,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": dict(source),
        "normal_definition": normal_definition,
        "population": dict(population or {}),
        "n_samples": {layer: len(grid) for layer, grid in grids.items()},
        "tie_mass_at_zero": {
            layer: round(tie_mass(samples.get(layer, grid), 0.0), 6)
            for layer, grid in grids.items()
        },
        "quantiles": {layer: list(grid) for layer, grid in grids.items()},
        "final_score_quantiles": quantile_grid(finals, n=DEFAULT_GRID_N),
        "derived_thresholds": {**thresholds, "from_percentile": dict(percentiles)},
        # validate_startup ใช้ตรวจว่า L4_GAMMA ใน env ตรงกับที่ใช้หาเกณฑ์
        "fusion": {"gamma": gamma, "config": fusion_config},
        "reachability": reachability(grids, gamma=gamma, thresholds=thresholds),
        "checks": checks,
    }


def validate_artifact(artifact: dict, min_samples: int = 1000) -> list[str]:
    """ตรวจก่อนนำไปใช้ — คืนรายการปัญหา · ว่างเปล่า = ผ่าน.

    ตั้งใจคืนรายการแทนการ raise เพื่อให้เห็นปัญหาทุกข้อในรอบเดียว ไม่ใช่แก้ทีละข้อ
    """
    problems: list[str] = []
    quantiles = artifact.get("quantiles") or {}
    n_samples = artifact.get("n_samples") or {}

    for layer in LAYERS:
        grid = quantiles.get(layer)
        if not grid:
            problems.append(f"ไม่มีตารางของชั้น {layer}")
            continue
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in grid):
            problems.append(f"ตารางของชั้น {layer} มีค่าที่ไม่ finite")
        elif list(grid) != sorted(grid):
            problems.append(f"ตารางของชั้น {layer} ไม่ได้เรียงจากน้อยไปมาก")
        count = n_samples.get(layer)
        if count is None:
            problems.append(f"ไม่ได้บันทึกจำนวนตัวอย่างของชั้น {layer}")
        elif count < min_samples:
            problems.append(
                f"ชั้น {layer} มีตัวอย่างแค่ {count} ตัว (ต้องการอย่างน้อย {min_samples})"
            )

    thresholds = artifact.get("derived_thresholds") or {}
    if not thresholds.get("from_percentile"):
        problems.append("ไม่ได้บันทึกว่าเกณฑ์มาจากเปอร์เซ็นไทล์ใด")
    ordered = [thresholds.get(k) for k in ("warn", "challenge", "block")]
    if all(isinstance(v, (int, float)) for v in ordered) and not (
        ordered[0] <= ordered[1] <= ordered[2]
    ):
        problems.append("เกณฑ์ไม่เรียงจากผ่อนไปเข้ม (warn <= challenge <= block)")

    if not artifact.get("final_score_quantiles"):
        problems.append("ไม่มี ECDF ของคะแนนรวม — แปลงเปอร์เซ็นไทล์เป็นเกณฑ์ไม่ได้")
    return problems


def write_artifact(path, artifact: dict) -> Path:
    """เขียนแบบกำหนดผลแน่นอน เพื่อให้ sha256 ซ้ำได้จากเนื้อเดียวกันบนทุกระบบ.

    เขียนเป็น bytes ไม่ใช่ `write_text` — บน Windows `write_text` แปลง \\n เป็น \\r\\n
    ทำให้ hash ขึ้นกับระบบที่สร้าง (เจอจริงกับตาราง v1 เมื่อ 17 ก.ย. 2569)
    """
    p = Path(path)
    text = json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    p.write_bytes(text.encode("utf-8"))
    return p


def sha256_of(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ══════════════════════════════════════════════════════════════════════════════
# บันทึก seed ที่ถูกใช้ — ห้ามใช้ซ้ำโดยไม่รู้ตัว (B68)
# ══════════════════════════════════════════════════════════════════════════════


def _load_ledger(path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — ไฟล์เสียต้องไม่ทำให้บันทึกเดิมหาย
        raise


def seeds_already_used(ledger_path, seeds) -> list[int]:
    """seed ไหนเคยถูกใช้ไปแล้วบ้าง — เรียกก่อนเริ่มรันเสมอ."""
    spent: set[int] = set()
    for entry in _load_ledger(ledger_path).values():
        for s in entry.get("seeds") or ():
            spent.add(int(s))
    return sorted(set(int(s) for s in seeds) & spent)


def record_seed_use(ledger_path, seeds, purpose: str, note: str = "") -> dict:
    """บันทึกว่า seed ชุดนี้ถูกเปิดใช้ทำอะไร — **ห้ามลบของเดิม**.

    เปิดซ้ำไม่ได้เขียนทับ แต่เพิ่ม `open_count` และขยับ `last_opened_at`
    เพราะการเปิดซ้ำคือข้อเท็จจริงที่ต้องอ่านย้อนได้ (B68)
    """
    ledger = _load_ledger(ledger_path)
    key = ",".join(str(int(s)) for s in seeds)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entry = ledger.get(key)
    if entry:
        entry["open_count"] = int(entry.get("open_count") or 1) + 1
        entry["last_opened_at"] = now
        if note:
            entry["note"] = note
    else:
        entry = {
            "seeds": [int(s) for s in seeds],
            "purpose": purpose,
            "first_opened_at": now,
            "last_opened_at": now,
            "open_count": 1,
        }
        if note:
            entry["note"] = note
        ledger[key] = entry
    Path(ledger_path).write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return entry
