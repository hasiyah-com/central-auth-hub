"""แบ่งข้อมูลสี่ส่วน + ตรวจ leakage — ใช้ generator เดิม ไม่แตะ logic การตัดสิน.

**ทำไมต้องสี่ส่วน ไม่ใช่สาม:** ถ้าใช้ validation ชุดเดียวทำทั้ง fit ECDF และเลือก
gamma/threshold ค่าที่เลือกจะ overfit กับ ECDF ที่มาจากข้อมูลชุดเดียวกัน ทำให้ผล
มองโลกในแง่ดีเกินจริงโดยไม่มีใครเห็น (รูปแบบเดียวกับ optimism bias ที่วัดได้ในรอบก่อน)

    train                 สร้างโปรไฟล์ผู้ใช้ + fit IsolationForest
    validation-calibration  fit empirical CDF ของแต่ละชั้น (normal ล้วน)
    validation-tuning       เลือก gamma และ threshold
    final holdout           วัดครั้งเดียวหลัง freeze

`val_ft` ของ generator เรียงตามเวลาอยู่แล้ว จึงแบ่งครึ่งตามลำดับ = temporal split
ดัชนีที่ใช้แบ่งถูกบันทึกลง artifact เพื่อให้ทำซ้ำได้เป๊ะ
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ML = Path(__file__).resolve().parents[1]
if str(ML) not in sys.path:
    sys.path.insert(0, str(ML))

import gen_v3 as G3  # noqa: E402

# สัดส่วนการแบ่ง validation — ครึ่งแรก calibrate ครึ่งหลัง tune
CALIBRATION_FRACTION = 0.5

# field ที่ใช้ระบุ "เหตุการณ์เดียวกัน" ตอนตรวจ leakage
# เทียบแค่ timestamp ไม่พอ — เคยเจอ U03 เวลาเดียวกันแต่คนละเหตุการณ์จริง
ROW_FIELDS = (
    "created_at",
    "logout_at",
    "device_signature",
    "subsystem",
    "duration_min",
    "login_method",
    "login_successful",
    "user_agent",
    "passkey_age_days",
    "permission_change_age",
    "concurrent_session_count",
)


@dataclass
class UserSplit:
    """ข้อมูลของผู้ใช้หนึ่งคน แบ่งครบสี่ส่วน."""

    alias: str
    train_raw: list = field(default_factory=list)
    train_ft: list = field(default_factory=list)
    cal_normal_ft: list = field(default_factory=list)
    tune_normal_ft: list = field(default_factory=list)
    tune_attacks: list = field(default_factory=list)  # [(row, vec)]
    holdout_normal: list = field(default_factory=list)  # [(row, vec)]
    holdout_attacks: list = field(default_factory=list)  # [(row, vec)]
    cal_slice: tuple[int, int] = (0, 0)
    tune_slice: tuple[int, int] = (0, 0)


def build(
    users_xlsx: Path, seed: int, size: int, raw: dict | None = None
) -> dict[str, UserSplit]:
    """สร้างข้อมูลหนึ่ง seed แล้วแบ่งสี่ส่วน — ทุก config ต้องใช้ผลของฟังก์ชันนี้ร่วมกัน.

    `raw` ส่งเข้ามาได้เมื่อวนหลาย size บน seed เดียวกัน เพื่อไม่ต้อง generate ซ้ำ
    (ผลลัพธ์เหมือนกันทุกประการ เพราะ `build_seed` deterministic ต่อ seed)
    """
    raw = raw if raw is not None else G3.build_seed(users_xlsx, seed)
    out: dict[str, UserSplit] = {}
    for alias, u in raw.items():
        tr_raw, tr_ft = G3.nested_subset(u, size)
        val = u["val_ft"]
        cut = int(len(val) * CALIBRATION_FRACTION)
        out[alias] = UserSplit(
            alias=alias,
            train_raw=tr_raw,
            train_ft=tr_ft,
            cal_normal_ft=val[:cut],
            tune_normal_ft=val[cut:],
            tune_attacks=list(u["dev_attacks"]),
            holdout_normal=list(u["test"]),
            holdout_attacks=list(u["final_attacks"]),
            cal_slice=(0, cut),
            tune_slice=(cut, len(val)),
        )
    return out


def _sig(rows) -> set:
    return {tuple(str(r.get(k)) for k in ROW_FIELDS) for r in rows}


def check_leakage(splits: dict[str, UserSplit]) -> dict:
    """holdout ต้องไม่ทับ train/calibration/tuning — เทียบทั้งแถว ไม่ใช่แค่ timestamp."""
    overlap = 0
    total = 0
    for u in splits.values():
        seen = _sig(u.train_raw)
        hold = _sig([r for r, _ in u.holdout_normal]) | _sig(
            [r for r, _ in u.holdout_attacks]
        )
        overlap += len(seen & hold)
        total += len(hold)
    return {"overlapping_rows": overlap, "holdout_rows": total, "clean": overlap == 0}


def _auc_with_ties(a, n):
    """AUC (Mann-Whitney) ที่ **จัดการค่าเสมอด้วย mid-rank**.

    ตัวตรวจเดิมใช้ `ranks[order] = arange(1, N+1)` ซึ่งให้อันดับต่างกันกับค่าที่
    เท่ากัน โดยขึ้นกับลำดับใน array -> ฟีเจอร์ที่ฝั่งหนึ่งผูกที่ค่าเดียวทั้งหมด
    (เช่น attack ทุกแถวมี passkey_last_used_days = 0) จะได้ AUC = 1.0 ปลอม
    ทั้งที่แยกไม่ได้จริง เพราะ normal ส่วนใหญ่ก็เป็น 0 เหมือนกัน

    พบ 2 ก.ย. 2569 — บั๊กนี้สืบทอดมาจาก exp_final_gate.py จึงทำให้ผลการตรวจ
    shortcut ของรอบก่อนเชื่อถือไม่ได้เช่นกัน (ทั้งที่รายงานว่า "ไม่พบ")
    """
    import numpy as np

    allv = np.concatenate([a, n])
    order = np.argsort(allv, kind="mergesort")
    sorted_v = allv[order]
    ranks = np.empty(len(allv), dtype=float)
    i = 0
    while i < len(sorted_v):
        j = i
        while j + 1 < len(sorted_v) and sorted_v[j + 1] == sorted_v[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0  # mid-rank ของกลุ่มที่เสมอกัน
        i = j + 1
    auc = (ranks[: len(a)].sum() - len(a) * (len(a) + 1) / 2) / (len(a) * len(n))
    return max(auc, 1 - auc)


def check_shortcut(attack_vecs: list, normal_vecs: list, feature_names) -> list:
    """หาฟีเจอร์เดี่ยวที่แยก attack/normal ได้เกือบสมบูรณ์ = generator รั่ว.

    เคยเจอจริง: `success_10m` ฝั่ง normal เป็น 0 เสมอ ทำให้ recall พุ่ง 90.9%
    ซึ่งเป็นการเรียนทางลัด ไม่ใช่ความสามารถจริง
    """
    import numpy as np

    if not attack_vecs or not normal_vecs:
        return []
    A = np.asarray(attack_vecs, dtype=float)
    N = np.asarray(normal_vecs, dtype=float)
    bad = []
    for j, name in enumerate(feature_names):
        a, n = A[:, j], N[:, j]
        if a.std() < 1e-12 and n.std() < 1e-12:
            continue
        auc = _auc_with_ties(a, n)
        cover = float(((a >= n.min()) & (a <= n.max())).mean())
        if auc > 0.99 or cover < 0.05:
            bad.append(
                {"feature": name, "auc": round(auc, 4), "coverage": round(cover, 3)}
            )
    return bad


class ECDF:
    """empirical CDF ต่อชั้น — fit จาก **calibration split เท่านั้น**.

    ห้าม fit จาก tuning หรือ holdout เด็ดขาด · ค่าที่คืนคือสัดส่วนของ login ปกติ
    ที่คะแนนไม่เกินค่าที่เห็น ซึ่งทำให้ทุกชั้นเทียบกันได้บนสเกลเดียว
    """

    def __init__(self) -> None:
        self._q: dict[str, list[float]] = {}

    def fit(self, layer: str, normal_scores: list[float]) -> None:
        self._q[layer] = sorted(float(x) for x in normal_scores)

    def __call__(self, layer: str, raw: float) -> float:
        """สัดส่วนของ login ปกติที่คะแนน **ต่ำกว่า** ค่านี้อย่างเคร่งครัด.

        คะแนนที่ตรงกับค่าที่พบบ่อย (เช่น 0.0 ซึ่ง login ปกติส่วนใหญ่ได้) ต้องได้
        evidence ต่ำ ไม่ใช่สูง · ใช้ bisect_left = สัดส่วนที่ **ต่ำกว่าอย่างเคร่งครัด**
        ถ้าใช้ bisect_right ค่าที่พบบ่อยที่สุดจะถูกนับว่าสูงกว่าทุกคนที่เท่ากัน
        -> login ปกติที่สุดได้หลักฐาน 1.0 (bug ที่ smoke test จับได้ 2 ก.ย. 2569)
        """
        import bisect

        q = self._q.get(layer)
        if not q:
            return min(max(float(raw), 0.0), 1.0)
        return bisect.bisect_left(q, float(raw)) / len(q)

    def to_artifact(self) -> dict:
        """เก็บควอนไทล์ลง artifact — จำนวนจุดจำกัดไว้ให้ไฟล์ไม่ใหญ่เกินไป."""
        out = {}
        for layer, q in self._q.items():
            if not q:
                continue
            step = max(1, len(q) // 512)
            out[layer] = [round(v, 6) for v in q[::step]]
        return out

    @property
    def layers(self) -> list[str]:
        return sorted(self._q)
