"""Cluster / hierarchical bootstrap — ช่วงเชื่อมั่นที่เคารพโครงสร้างข้อมูล.

**ทำไมไม่ใช้ bootstrap ธรรมดา:** เหตุการณ์ของผู้ใช้คนเดียวกันไม่เป็นอิสระต่อกัน
(คนที่พฤติกรรมแปลกจะแปลกทั้งชุด) การสุ่มรายเหตุการณ์จะทำให้ CI **แคบเกินจริง**
และรายงานความมั่นใจสูงกว่าที่ข้อมูลรองรับ

    cluster bootstrap        สุ่ม**ผู้ใช้**ทั้งคน (พร้อมเหตุการณ์ทั้งหมด) แบบมีคืน
    hierarchical bootstrap   สุ่มผู้ใช้ แล้วสุ่มเหตุการณ์ภายในผู้ใช้ที่ถูกเลือกอีกชั้น

ใช้ hierarchical เมื่อจำนวนเหตุการณ์ต่อคนต่างกันมาก (ซึ่งเป็นกรณีของข้อมูลชุดนี้)
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence


def cluster_bootstrap(
    clusters: dict[str, Sequence],
    stat: Callable[[list], float],
    *,
    n_boot: int = 2000,
    seed: int = 0,
    hierarchical: bool = True,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """คืน (ค่าที่วัดได้, ขอบล่าง, ขอบบน) ที่ระดับความเชื่อมั่น 1-alpha.

    `clusters`  {user_id: [รายการผลต่อเหตุการณ์]}
    `stat`      ฟังก์ชันที่รับรายการผลรวมทุกคน แล้วคืนตัวเลขเดียว
    """
    keys = list(clusters)
    if not keys:
        return 0.0, 0.0, 0.0
    flat = [x for k in keys for x in clusters[k]]
    if not flat:
        return 0.0, 0.0, 0.0

    point = stat(flat)
    rng = random.Random(seed)
    dist: list[float] = []
    for _ in range(n_boot):
        sample: list = []
        for _ in range(len(keys)):
            k = keys[rng.randrange(len(keys))]
            rows = clusters[k]
            if not rows:
                continue
            if hierarchical:
                sample.extend(rows[rng.randrange(len(rows))] for _ in range(len(rows)))
            else:
                sample.extend(rows)
        if sample:
            dist.append(stat(sample))
    if not dist:
        return point, point, point
    dist.sort()
    lo = dist[int((alpha / 2) * len(dist))]
    hi = dist[min(len(dist) - 1, int((1 - alpha / 2) * len(dist)))]
    return point, lo, hi


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Wilson score interval — สำหรับสัดส่วนที่เหตุการณ์เป็นอิสระต่อกันจริง.

    ใช้กับตัวเลขระดับ**แคมเปญ** ที่นับครั้งเดียวต่อแคมเปญ · สำหรับตัวเลขระดับ
    เหตุการณ์ให้ใช้ cluster bootstrap แทน เพราะเหตุการณ์ไม่เป็นอิสระ
    """
    import math

    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)
