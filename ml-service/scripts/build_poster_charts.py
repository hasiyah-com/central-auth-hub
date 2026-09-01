"""สร้างกราฟสำหรับโปสเตอร์วิชาการ (PNG ความละเอียดสูง) — 3 ก้อน.

    python ml-service/scripts/build_poster_charts.py --out docs/poster_charts

สร้างทั้งสองธีมในรอบเดียว:
    *_dark.png   พื้นหลังโปร่งใส + ตัวอักษรสว่าง — วางบนโปสเตอร์พื้นเข้ม (navy)
    *_light.png  พื้นหลังขาว + ตัวอักษรเข้ม     — วางบนโปสเตอร์พื้นสว่าง หรือพิมพ์เดี่ยว

ตัวเลขทุกตัวมาจากรายงานที่ freeze ไว้ ระบุแหล่งที่มาไว้ในตัวแปร SOURCE ของแต่ละก้อน
**ห้ามแก้ตัวเลขในไฟล์นี้โดยไม่อัปเดตรายงานต้นทาง**

ไม่มี PII: ข้อมูลทั้งหมดเป็นค่ารวมเชิงสถิติ
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

for name in ("Leelawadee UI", "Tahoma", "Angsana New"):
    if name in {f.name for f in font_manager.fontManager.ttflist}:
        plt.rcParams["font.family"] = name
        break

# ── ธีม ────────────────────────────────────────────────────────────────
DARK = dict(
    bg="none",
    fg="#ECEFF4",
    sub="#B0BEC5",
    grid="#8C9EFF",
    c1="#4FC3F7",
    c2="#4DB6AC",
    c3="#FFD54F",
    bad="#EF5350",
    mute="#78909C",
)
LIGHT = dict(
    bg="white",
    fg="#1A237E",
    sub="#455A64",
    grid="#90A4AE",
    c1="#1565C0",
    c2="#00838F",
    c3="#EF6C00",
    bad="#C62828",
    mute="#90A4AE",
)


def _setup(T):
    plt.rcParams.update(
        {
            "figure.dpi": 300,
            "savefig.dpi": 300,
            "axes.grid": True,
            "grid.alpha": 0.20,
            "grid.linestyle": "--",
            "grid.color": T["grid"],
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.spines.left": False,
            "axes.spines.bottom": True,
            "axes.edgecolor": T["sub"],
            "text.color": T["fg"],
            "axes.labelcolor": T["fg"],
            "xtick.color": T["fg"],
            "ytick.color": T["sub"],
            "font.size": 15,
            "axes.titlesize": 20,
            "axes.titleweight": "bold",
        }
    )


def save(fig, out: Path, name: str, T) -> None:
    p = out / name
    fig.savefig(
        p,
        bbox_inches="tight",
        facecolor=("none" if T["bg"] == "none" else T["bg"]),
        transparent=(T["bg"] == "none"),
    )
    plt.close(fig)
    print(f"  [ok] {p.name}")


# ═══════════════════════════════════════════════════════════════════════
# ก้อนที่ 1 — ผลหลักบนชุดที่โมเดลไม่เคยเห็น
# SOURCE: hub/backend/tests/reports/exp_final_gate_2026-08-26.md §2 (size 5000)
#         Recall 61.9 [60.2,63.6] · Precision 69.1 [67.4,70.7] · F1 คำนวณจาก P,R
def fig1_headline(out: Path, T, suffix: str) -> None:
    _setup(T)
    labels = ["Recall", "Precision", "F1-score"]
    vals = [61.9, 69.1, 65.3]
    fig, ax = plt.subplots(figsize=(7.6, 5.0))
    bars = ax.bar(labels, vals, color=[T["c1"], T["c2"], T["c3"]], width=0.58, zorder=3)
    # วาดแถบ CI เฉพาะสองตัวที่วัดมาจริง — F1 เป็นค่าคำนวณจาก P,R จึงไม่มี CI
    # (ถ้าวาดด้วย yerr=0 จะได้เส้นแบน ซึ่งอ่านว่า "CI แคบมาก" = สื่อผิด)
    ax.errorbar(
        labels[:2],
        vals[:2],
        yerr=[[1.7, 1.7], [1.7, 1.6]],
        fmt="none",
        ecolor=T["fg"],
        elinewidth=2,
        capsize=9,
        capthick=2,
        zorder=4,
    )
    for b, v in zip(bars, vals):
        ax.text(
            b.get_x() + b.get_width() / 2,
            v + 4.2,
            f"{v:.1f}%",
            ha="center",
            fontsize=21,
            fontweight="bold",
            color=T["fg"],
        )

    ax.set_ylim(0, 100)
    ax.set_ylabel("%", fontsize=16, rotation=0, labelpad=18, va="center")
    ax.set_yticks([0, 20, 40, 60, 80, 100])
    ax.tick_params(axis="x", labelsize=17, pad=8)
    ax.set_title("ผลการตรวจจับบนชุดข้อมูลที่โมเดลไม่เคยเห็น", color=T["fg"], pad=16)
    ax.text(
        0.5,
        -0.155,
        "held-out · seeds 101–105 · 5,000 เหตุการณ์/คน · แถบคือช่วงเชื่อมั่น 95% · F1 คำนวณจาก P และ R",
        transform=ax.transAxes,
        ha="center",
        fontsize=13,
        color=T["sub"],
    )
    ax.text(
        0.5,
        -0.235,
        "Challenge FPR 1.5%   ·   L3 FPR 0.7%   ·   ตรวจจับระดับแคมเปญ 96.7%",
        transform=ax.transAxes,
        ha="center",
        fontsize=13.5,
        color=T["fg"],
        fontweight="bold",
    )
    save(fig, out, f"poster1_results_{suffix}.png", T)


# ═══════════════════════════════════════════════════════════════════════
# ก้อนที่ 2 — การเลือก threshold (การตัดสินใจเชิงวิศวกรรม)
# SOURCE: hub/backend/tests/reports/exp_thr_and_l2_fix_2026-08-26.md §1
#         quantile sweep บน final holdout · เลือก p99.9 เป็นจุดเดียวที่ FPR <= 1%
def fig2_threshold(out: Path, T, suffix: str) -> None:
    _setup(T)
    q = ["p99", "p99.3", "p99.5", "p99.7", "p99.9"]
    fpr = [2.14, 1.76, 1.52, 1.19, 0.79]
    uniq = [5.31, 4.39, 3.66, 3.35, 2.43]
    x = list(range(len(q)))

    fig, ax = plt.subplots(figsize=(8.2, 5.0))
    ax.plot(
        x,
        uniq,
        marker="o",
        ms=10,
        lw=3,
        color=T["c2"],
        label="สิ่งที่ชั้นนี้เห็นคนเดียว",
        zorder=3,
    )
    ax.plot(
        x,
        fpr,
        marker="s",
        ms=10,
        lw=3,
        color=T["bad"],
        label="อัตราเตือนผิดพลาด",
        zorder=3,
    )

    ax.axhline(1.0, ls=":", lw=2.2, color=T["c3"], zorder=2)
    ax.text(0.06, 1.18, "งบประมาณ 1%", fontsize=13, color=T["c3"], fontweight="bold")

    # จุดที่เลือก
    ax.scatter(
        [4], [0.79], s=460, facecolors="none", edgecolors=T["c3"], lw=3.2, zorder=5
    )
    ax.annotate(
        "จุดที่เลือก",
        xy=(4, 0.79),
        xytext=(2.85, 0.15),
        fontsize=14.5,
        color=T["c3"],
        fontweight="bold",
        arrowprops=dict(arrowstyle="->", color=T["c3"], lw=2.2),
    )

    for i, (f, u) in enumerate(zip(fpr, uniq)):
        ax.text(i, u + 0.26, f"{u:.2f}", ha="center", fontsize=12.5, color=T["c2"])
        ax.text(i, f - 0.42, f"{f:.2f}", ha="center", fontsize=12.5, color=T["bad"])

    ax.set_xticks(x)
    ax.set_xticklabels(q, fontsize=15)
    ax.set_ylim(-0.15, 6.2)
    ax.set_ylabel("%", fontsize=16, rotation=0, labelpad=18, va="center")
    ax.set_xlabel("เกณฑ์ (quantile) ของชั้นตรวจจับ", fontsize=14, labelpad=8)
    leg = ax.legend(loc="upper right", fontsize=13.5, frameon=False)
    for t in leg.get_texts():
        t.set_color(T["fg"])
    ax.set_title("การเลือกเกณฑ์ — แลกความไวเพื่อคุมการเตือนผิดพลาด", color=T["fg"], pad=16)
    ax.text(
        0.5,
        -0.21,
        "ยอมให้ตรวจพบน้อยลงครึ่งหนึ่ง (5.31% เหลือ 2.43%) เพื่อให้อัตราเตือนผิดพลาดอยู่ในงบ (2.14% เหลือ 0.79%)",
        transform=ax.transAxes,
        ha="center",
        fontsize=12.5,
        color=T["sub"],
    )
    save(fig, out, f"poster2_threshold_{suffix}.png", T)


# ═══════════════════════════════════════════════════════════════════════
# ก้อนที่ 3 — เปรียบเทียบโมเดล (in-sample · รอบคัดเลือกโมเดล)
# SOURCE: hub/backend/tests/reports/benchmark_rba_robustness_2026-06-15.md §1
#         20 seeds · 23 features · อัตราการโจมตี 1.38% -> เส้นฐาน PR-AUC = 0.0138
def fig3_models(out: Path, T, suffix: str) -> None:
    _setup(T)
    models = ["OneClassSVM", "IsolationForest", "LocalOutlierFactor"]
    pr = [0.809, 0.747, 0.575]
    pr_err = [0.017, 0.018, 0.018]
    roc = [0.965, 0.925, 0.779]
    x = list(range(len(models)))

    fig, ax = plt.subplots(figsize=(8.6, 5.0))
    b1 = ax.bar(
        [i - 0.2 for i in x],
        pr,
        width=0.38,
        color=T["c1"],
        yerr=pr_err,
        ecolor=T["fg"],
        capsize=7,
        label="PR-AUC",
        zorder=3,
    )
    b2 = ax.bar(
        [i + 0.2 for i in x],
        roc,
        width=0.38,
        color=T["mute"],
        label="ROC-AUC",
        zorder=3,
    )
    for bars, vals in ((b1, pr), (b2, roc)):
        for b, v in zip(bars, vals):
            ax.text(
                b.get_x() + b.get_width() / 2,
                v + 0.045,
                f"{v:.3f}",
                ha="center",
                fontsize=14,
                fontweight="bold",
                color=T["fg"],
            )

    # เส้นฐานของ PR-AUC = สัดส่วนคลาสบวก — ขาดบรรทัดนี้ ค่า 0.747 อ่านไม่ออก
    ax.axhline(0.0138, ls="--", lw=2.2, color=T["c3"], zorder=2)
    ax.text(
        2.52,
        0.055,
        "เส้นฐาน PR-AUC = 0.0138\n(อัตราการโจมตี 1.38%)",
        fontsize=12.5,
        color=T["c3"],
        ha="right",
        fontweight="bold",
    )

    # เน้นโมเดลที่เลือกใช้จริง
    ax.get_xticklabels()
    ax.set_xticks(x)
    ax.set_xticklabels(models, fontsize=14.5)
    ax.get_xticklabels()[1].set_color(T["c3"])
    ax.get_xticklabels()[1].set_fontweight("bold")
    # เผื่อที่ว่างด้านบนให้ legend ไม่ทับป้ายตัวเลขของแท่งที่สูงสุด (0.965 + ป้าย)
    ax.set_ylim(0, 1.34)
    ax.set_yticks([0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_ylabel("AUC", fontsize=15, rotation=0, labelpad=26, va="center")
    leg = ax.legend(
        loc="upper left",
        fontsize=13.5,
        frameon=False,
        ncol=2,
        bbox_to_anchor=(0.0, 1.005),
    )
    for t in leg.get_texts():
        t.set_color(T["fg"])
    ax.set_title("เปรียบเทียบโมเดลตรวจจับความผิดปกติ", color=T["fg"], pad=16)
    ax.text(
        0.5,
        -0.155,
        "20 seeds · 23 คุณลักษณะ · การประเมินแบบ in-sample (คนละเงื่อนไขกับผลในกราฟแรก)",
        transform=ax.transAxes,
        ha="center",
        fontsize=12.5,
        color=T["sub"],
    )
    ax.text(
        0.5,
        -0.235,
        "เลือก IsolationForest: ที่จุดทำงานจริง (≤1%) F1 ต่างกันเพียง 0.802 vs 0.818 "
        "แต่ชนะด้านการอธิบายผล ความเร็ว และการขยายขนาด",
        transform=ax.transAxes,
        ha="center",
        fontsize=12.5,
        color=T["fg"],
        fontweight="bold",
    )
    save(fig, out, f"poster3_models_{suffix}.png", T)


FIGS = [fig1_headline, fig2_threshold, fig3_models]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("docs/poster_charts"))
    args = ap.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    print(f"สร้างกราฟโปสเตอร์ -> {out}")
    for T, suffix in ((DARK, "dark"), (LIGHT, "light")):
        for f in FIGS:
            f(out, T, suffix)
    print("เสร็จ — ใช้ *_dark.png บนโปสเตอร์พื้นเข้ม · *_light.png บนพื้นสว่าง")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
