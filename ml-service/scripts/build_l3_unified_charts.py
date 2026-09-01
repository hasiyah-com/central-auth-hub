"""สร้างกราฟสำหรับรายงานผลการทดลองรอบ 2 — L3 Unified (.docx).

ตัวเลขทุกตัวมาจากรายงานที่ freeze ไว้ (tag rba-expert-review-2026-09-01)
แหล่งหลัก: hub/backend/tests/reports/l3_unified_2026-08-31.md
แต่ละฟังก์ชันระบุที่มาไว้ในคอมเมนต์ — ตรวจย้อนได้

    python ml-service/scripts/build_l3_unified_charts.py --out docs/report_charts_l3

ไม่มี PII: ไม่มีอีเมล/ชื่อจริง/โฮสต์ — ข้อมูล session อ้างเป็นค่ารวมเท่านั้น
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

# ── ฟอนต์ไทย: ไม่ตั้งจะได้กล่องสี่เหลี่ยมแทนตัวอักษร ──
for name in ("Leelawadee UI", "Tahoma", "Angsana New"):
    if name in {f.name for f in font_manager.fontManager.ttflist}:
        plt.rcParams["font.family"] = name
        break
plt.rcParams.update(
    {
        "figure.dpi": 160,
        "savefig.dpi": 160,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "grid.linestyle": "--",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "font.size": 10,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
    }
)

C_GOOD, C_BAD, C_L1, C_L2, C_L3, C_L4 = (
    "#2E7D32",
    "#C62828",
    "#1565C0",
    "#00838F",
    "#EF6C00",
    "#4527A0",
)
C_MUTE, C_WARN = "#9E9E9E", "#F9A825"


def save(fig, out: Path, name: str) -> None:
    p = out / f"{name}.png"
    fig.tight_layout()
    fig.savefig(p, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  [ok] {p.name}")


# ═══════════════════════════════════════════════════════════════════════
# 1. การตัดสินเปลี่ยนไปกี่ครั้ง — ระบบที่วัด vs ระบบที่รัน
# ที่มา: l3_unified_2026-08-31.md §1.2 (login_sessions 1,024 รายการ)
def fig_decision_shift(out: Path) -> None:
    labels = ["allow", "warn", "challenge", "block"]
    # นับปลายทางของแต่ละคอนฟิก จากตาราง transition
    without = [453 + 65, 152 + 41, 5 + 22, 286]  # L1+L2 เท่านั้น
    with_if = [453, 152 + 65, 5 + 41, 286 + 22]  # production เดิม (บวก IForest)

    x = range(len(labels))
    fig, ax = plt.subplots(figsize=(7.6, 4.3))
    b1 = ax.bar(
        [i - 0.2 for i in x],
        without,
        width=0.38,
        color=C_L1,
        label="คอนฟิกที่การทดลองวัด (IForest = 0)",
    )
    b2 = ax.bar(
        [i + 0.2 for i in x],
        with_if,
        width=0.38,
        color=C_BAD,
        label="คอนฟิกที่ production รันจริง (บวก IForest)",
    )
    for bars in (b1, b2):
        for b in bars:
            ax.text(
                b.get_x() + b.get_width() / 2,
                b.get_height() + 6,
                f"{int(b.get_height())}",
                ha="center",
                fontsize=9,
            )
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel("จำนวน session")
    ax.set_ylim(0, 600)
    ax.legend(loc="upper right", fontsize=9)
    ax.set_title("รูปที่ 1  ผลการตัดสินของสองคอนฟิก บน session จริงชุดเดียวกัน (n = 1,024)")
    save(fig, out, "fig01_decision_shift")


# 2. 128 ครั้งที่เปลี่ยน — แยกตามทิศทาง
# ที่มา: l3_unified_2026-08-31.md §1.2
def fig_transitions(out: Path) -> None:
    rows = [
        ("challenge  ->  block", 22, C_BAD),
        ("warn  ->  challenge", 41, "#EF6C00"),
        ("allow  ->  warn", 65, C_WARN),
    ]
    fig, ax = plt.subplots(figsize=(7.6, 3.4))
    ys = range(len(rows))
    bars = ax.barh(
        list(ys), [r[1] for r in rows], color=[r[2] for r in rows], height=0.55
    )
    for b, (_, n, _) in zip(bars, rows):
        ax.text(
            b.get_width() + 1.2,
            b.get_y() + b.get_height() / 2,
            f"{n} ครั้ง  ({n / 1024 * 100:.1f}%)",
            va="center",
            fontsize=10,
        )
    ax.set_yticks(list(ys))
    ax.set_yticklabels([r[0] for r in rows])
    ax.set_xlabel("จำนวน session ที่ผลการตัดสินถูกยกระดับโดย IForest")
    ax.set_xlim(0, 88)
    ax.set_title("รูปที่ 2  128 จาก 1,024 ครั้ง (12.5%) ที่ชั้นซึ่งการทดลองวัดว่าเป็นศูนย์ เป็นผู้ตัดสิน")
    ax.text(
        44,
        -0.85,
        "ทุกกรณีเป็นการยกระดับความเข้ม ไม่มีกรณีไหนผ่อนลง " "เพราะ map_score บวกอย่างเดียว",
        ha="center",
        fontsize=9,
        color=C_MUTE,
    )
    save(fig, out, "fig02_transitions")


# 3. map_score บวกเท่าไหร่ เทียบกับเกณฑ์ตัดสิน
# ที่มา: iforest_scorer.py::map_score · risk_aggregator.py::THRESHOLDS
def fig_map_score(out: Path) -> None:
    xs = [0.0, 0.3, 0.3, 0.5, 0.5, 0.7, 0.7, 1.0]
    ys = [0.0, 0.0, 0.10, 0.10, 0.20, 0.20, 0.40, 0.40]
    fig, ax = plt.subplots(figsize=(7.6, 4.2))
    ax.plot(xs, ys, lw=2.6, color=C_L3, solid_joinstyle="miter")
    ax.fill_between(xs, 0, ys, color=C_L3, alpha=0.12)

    for thr, lab, col in (
        (0.5, "warn 0.50", C_WARN),
        (0.7, "challenge 0.70", "#EF6C00"),
        (0.85, "block 0.85", C_BAD),
    ):
        ax.axhline(thr, ls=":", lw=1.5, color=col)
        ax.text(1.005, thr, lab, va="center", fontsize=9, color=col)

    ax.annotate(
        "สูงสุด +0.40\n= 57% ของเกณฑ์ challenge",
        xy=(0.85, 0.40),
        xytext=(0.42, 0.60),
        fontsize=9.5,
        color=C_BAD,
        arrowprops=dict(arrowstyle="->", color=C_BAD, lw=1.4),
    )
    ax.set_xlabel("คะแนนดิบจาก IsolationForest (anomaly score)")
    ax.set_ylabel("คะแนนที่บวกเข้าความเสี่ยงรวม")
    ax.set_xlim(0, 1.0)
    ax.set_ylim(0, 0.95)
    ax.set_title("รูปที่ 3  IForest บวกเข้าคะแนนเท่าไหร่ เทียบกับเกณฑ์ตัดสิน")
    save(fig, out, "fig03_map_score")


# 4. สองแกนของการตัดสินใจ (แผนภาพ)
# ที่มา: l3_unified_2026-08-31.md §4-5
def fig_two_axes(out: Path) -> None:
    fig, ax = plt.subplots(figsize=(8.0, 4.6))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6.2)
    ax.axis("off")
    ax.grid(False)

    def box(x, y, w, h, text, fc, ec, fs=9.5, bold=False):
        ax.add_patch(
            FancyBboxPatch(
                (x, y), w, h, boxstyle="round,pad=0.08", fc=fc, ec=ec, lw=1.6
            )
        )
        ax.text(
            x + w / 2,
            y + h / 2,
            text,
            ha="center",
            va="center",
            fontsize=fs,
            fontweight="bold" if bold else "normal",
        )

    def arrow(x1, y1, x2, y2, col):
        ax.add_patch(
            FancyArrowPatch(
                (x1, y1),
                (x2, y2),
                arrowstyle="-|>",
                mutation_scale=15,
                lw=1.8,
                color=col,
            )
        )

    box(0.2, 2.5, 1.7, 1.2, "login\nเหตุการณ์", "#F5F5F5", C_MUTE)

    box(2.5, 4.2, 2.3, 0.95, "L1  Rule Engine", "#E3F2FD", C_L1)
    box(2.5, 3.05, 2.3, 0.95, "L2  Behavior", "#E0F2F1", C_L2)
    box(5.6, 3.6, 1.9, 1.5, "L4\nAggregation", "#EDE7F6", C_L4, bold=True)
    box(
        8.0,
        3.85,
        1.8,
        1.0,
        "access_decision\nallow / warn / challenge / block",
        "#EDE7F6",
        C_L4,
        fs=8.5,
        bold=True,
    )

    box(2.5, 1.35, 2.3, 0.95, "L3 point view\nIForest 23 ฟีเจอร์", "#FFF3E0", C_L3, fs=9)
    box(2.5, 0.2, 2.3, 0.95, "L3 sequence view\nresidual 18 มิติ", "#FFF3E0", C_L3, fs=9)
    box(5.6, 0.6, 1.9, 1.5, "L3\nรวมผล\n+ SHAP", "#FFF3E0", C_L3, bold=True)
    box(
        8.0,
        0.85,
        1.8,
        1.0,
        "monitoring_decision\nnormal / l3_investigate",
        "#FFF3E0",
        C_L3,
        fs=8.5,
        bold=True,
    )

    for y in (4.65, 3.5):
        arrow(1.9, 3.1, 2.5, y, C_MUTE)
    for y in (1.8, 0.65):
        arrow(1.9, 3.1, 2.5, y, C_MUTE)
    arrow(4.8, 4.65, 5.6, 4.5, C_L1)
    arrow(4.8, 3.5, 5.6, 4.2, C_L2)
    arrow(7.5, 4.35, 8.0, 4.35, C_L4)
    arrow(4.8, 1.8, 5.6, 1.6, C_L3)
    arrow(4.8, 0.65, 5.6, 1.1, C_L3)
    arrow(7.5, 1.35, 8.0, 1.35, C_L3)

    # เส้นกั้นสองแกน — เริ่มหลังกล่อง login เพราะ "เหตุการณ์" ป้อนเข้าทั้งสองแกนได้
    # สิ่งที่ห้ามข้ามคือ **ผลลัพธ์** ของ L3 ไม่ใช่ข้อมูลขาเข้า
    ax.plot([2.2, 9.9], [2.42, 2.42], ls="--", lw=1.4, color=C_BAD)
    ax.text(
        9.85,
        2.52,
        "ผลของ L3 ไม่ข้ามกลับขึ้นมา",
        ha="right",
        fontsize=9,
        color=C_BAD,
        fontweight="bold",
    )
    ax.text(
        0.15, 5.5, "แกนที่ 1 — ตัดสินสิทธิ์ผู้ใช้", fontsize=10.5, fontweight="bold", color=C_L4
    )
    ax.text(
        0.15,
        1.75,
        "แกนที่ 2 — เฝ้าระวัง\n(ไม่กระทบสิทธิ์)",
        fontsize=10.5,
        fontweight="bold",
        color=C_L3,
    )
    ax.set_title(
        "รูปที่ 4  โครงสร้างหลังแก้ — L3 ทั้งสองมุมมองออกทางแกนเฝ้าระวังเท่านั้น",
        fontsize=12,
        fontweight="bold",
    )
    save(fig, out, "fig04_two_axes")


# 5. ความแม่นของคำอธิบายตามระดับคะแนน — SHAP เสื่อมก่อนคะแนนอิ่มตัว
# ที่มา: l3_explainability_2026-09-01.md §3 (spike ครบ 6 มิติ x 7 ย่าน)
def fig_shap_saturation(out: Path) -> None:
    labels = [
        "0.48\n-0.51",
        "0.51\n-0.53",
        "0.54\n-0.60",
        "0.59\n-0.64",
        "0.69\n-0.71",
        "0.71\n-0.72",
        "0.7439\n(เพดาน)",
    ]
    shap = [6, 6, 6, 4, 3, 2, 1]
    dev = [6, 6, 6, 6, 6, 6, 6]
    x = list(range(len(labels)))

    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    ax.plot(
        x,
        dev,
        marker="o",
        ms=10,
        lw=3,
        color=C_GOOD,
        label="ส่วนเบี่ยงเบนรายมิติ (วิธีใหม่)",
        zorder=4,
    )
    ax.plot(
        x, shap, marker="s", ms=10, lw=3, color=C_BAD, label="SHAP (วิธีเดิม)", zorder=4
    )
    for i, (a, b) in enumerate(zip(dev, shap)):
        ax.text(i, a + 0.22, f"{a}/6", ha="center", fontsize=10, color=C_GOOD)
        ax.text(i, b - 0.45, f"{b}/6", ha="center", fontsize=10, color=C_BAD)

    # เส้นแบ่งจุดที่ระบบเริ่มขึ้นธง — SHAP เริ่มเสื่อมตรงนี้พอดี
    ax.axvspan(-0.5, 2.5, color=C_MUTE, alpha=0.10, zorder=1)
    ax.axvline(2.5, color=C_WARN, ls="--", lw=2, zorder=2)
    ax.text(
        2.42,
        6.55,
        "เกณฑ์แจ้งเตือน 0.5580",
        ha="right",
        fontsize=10.5,
        color=C_WARN,
        fontweight="bold",
    )
    ax.text(1.0, 0.72, "ยังไม่ขึ้นธง", ha="center", fontsize=10, color=C_MUTE)
    ax.text(
        4.5,
        0.72,
        "ขึ้นธงแล้ว — ย่านที่ใช้งานจริง",
        ha="center",
        fontsize=10.5,
        color=C_BAD,
        fontweight="bold",
    )

    ax.annotate(
        "คะแนนชนเพดานตรงนี้\n(หลังจาก SHAP พังไปแล้ว)",
        xy=(6, 1),
        xytext=(4.15, 3.1),
        fontsize=9.5,
        color=C_MUTE,
        ha="center",
        arrowprops=dict(arrowstyle="->", color=C_MUTE, lw=1.4),
    )

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9.5)
    ax.set_xlabel("ช่วงคะแนนความผิดปกติของ sequence view", fontsize=11.5, labelpad=8)
    ax.set_ylabel("จำนวนครั้งที่ชี้มิติถูก (จาก 6 มิติ)")
    ax.set_ylim(0, 7)
    ax.set_yticks([0, 2, 4, 6])
    ax.set_xlim(-0.5, 6.5)
    ax.legend(loc="center left", fontsize=10.5, framealpha=0.9)
    ax.set_title("รูปที่ 5  ความแม่นของคำอธิบาย ตามระดับคะแนน (B67)")
    ax.text(
        0.5,
        -0.245,
        "SHAP เริ่มชี้ผิดตั้งแต่จุดที่ระบบขึ้นธง ซึ่งเกิดก่อนคะแนนชนเพดาน "
        "· ส่วนเบี่ยงเบนรายมิติถูกต้องทุกย่าน",
        transform=ax.transAxes,
        ha="center",
        fontsize=10,
        color=C_MUTE,
    )
    save(fig, out, "fig05_shap_saturation")


# 6. ตัวอย่างคำอธิบายหลัก (robust deviation) จากผลจริง
# ที่มา: l3_explainability_2026-09-01.md §4 — window ที่ทำให้ scope พุ่งเด่น
#        history N(0,1) 1,500 แถว seed 42 · raw_score 0.7439 (ชนเพดาน)
def fig_shap_example(out: Path) -> None:
    feats = [
        "scope_ptp_w5",
        "scope_slope_w5",
        "scope_mean_w5",
        "passkey_age_log_ptp_w5",
        "weekday_usage_ptp_w5",
    ]
    dev = [25.00, 15.72, 9.41, 6.03, 5.80]
    is_target = [True, True, True, False, False]

    fig, ax = plt.subplots(figsize=(7.8, 3.8))
    ys = range(len(feats))
    bars = ax.barh(
        list(ys), dev, height=0.58, color=[C_GOOD if t else C_MUTE for t in is_target]
    )
    for b, v in zip(bars, dev):
        ax.text(
            b.get_width() + 0.45,
            b.get_y() + b.get_height() / 2,
            f"{v:.2f}",
            va="center",
            fontsize=10,
        )
    ax.set_yticks(list(ys))
    ax.set_yticklabels(feats, fontsize=9.5)
    ax.invert_yaxis()
    ax.set_xlim(0, 29)
    ax.set_xlabel("ส่วนเบี่ยงเบนจากพฤติกรรมปกติของผู้ใช้คนนี้ (เท่าของช่วงกระจาย)")
    ax.set_title("รูปที่ 6  คำอธิบายหลักที่ส่งให้ผู้ดูแลระบบ")
    ax.text(
        0.5,
        -0.30,
        "ด้านที่ถูกทำให้ผิดปกติในการทดสอบคือ scope — คำอธิบายชี้ scope "
        "ครบทั้งสามอันดับแรก (แท่งเขียว)",
        transform=ax.transAxes,
        ha="center",
        fontsize=10,
        color=C_MUTE,
    )
    ax.text(
        0.5,
        -0.40,
        "เหตุการณ์นี้คะแนนชนเพดาน (0.7439) ซึ่งเป็นย่านที่วิธีเดิมชี้ผิด",
        transform=ax.transAxes,
        ha="center",
        fontsize=10,
        color=C_BAD,
    )
    save(fig, out, "fig06_shap_example")


# 7. duplicate ratio — วัดคุณค่าที่ L3 เพิ่มขึ้นจริง
# ที่มา: l3_unified_2026-08-31.md §3 + test_duplicate_ratio_counts_only_flagged_events
def fig_duplicate_ratio(out: Path) -> None:
    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(9.0, 3.8), gridspec_kw={"width_ratios": [1.35, 1]}
    )

    events = ["#1\nchallenge", "#2\nblock", "#3\nallow", "#4\nallow"]
    uniq = [0, 0, 1, 1]
    bars = ax1.bar(
        events, [1] * 4, color=[C_GOOD if u else C_MUTE for u in uniq], width=0.55
    )
    for b, u in zip(bars, uniq):
        ax1.text(
            b.get_x() + b.get_width() / 2,
            0.5,
            "unique\nto L3" if u else "ซ้ำกับ\nL1/L2",
            ha="center",
            va="center",
            fontsize=9,
            color="white",
            fontweight="bold",
        )
    ax1.set_ylim(0, 1.35)
    ax1.set_yticks([])
    ax1.set_xlabel("เหตุการณ์ที่ L3 ขึ้นธง (เรียงตามเวลา) — พร้อม access_decision")
    ax1.set_title("แต่ละครั้งที่ยิง ถูกจัดประเภทอย่างไร", fontsize=10.5)

    ax2.pie(
        [2, 2],
        labels=["ซ้ำ (duplicate)", "L3 เห็นคนเดียว"],
        colors=[C_MUTE, C_GOOD],
        autopct="%1.0f%%",
        startangle=90,
        textprops={"fontsize": 9.5},
        wedgeprops={"edgecolor": "white", "linewidth": 2},
    )
    ax2.set_title("duplicate_ratio = 0.50\n(ตัวหาร duplicate_window = 4)", fontsize=10.5)

    fig.suptitle(
        "รูปที่ 7  ตัวชี้วัดที่ตอบว่า L3 คุ้มหรือไม่ — คำนวณตอน login จริง",
        fontsize=12,
        fontweight="bold",
        y=1.04,
    )
    save(fig, out, "fig07_duplicate_ratio")


# 8. ความครอบคลุมของการคุ้มครองสองแกน ก่อน/หลัง
# ที่มา: l3_unified_2026-08-31.md §0 + §5
def fig_coverage(out: Path) -> None:
    items = [
        "L3 sequence\nไม่แตะ access",
        "L3 point\nไม่แตะ access",
        "SHAP ของ\nsequence",
        "duplicate ratio\nใน runtime",
        "รวมเป็นผล\nL3 เดียว",
        "verify ข้าม\nแพลตฟอร์ม",
    ]
    before = [1, 0, 0, 0, 0, 0]
    after = [1, 1, 1, 1, 1, 1]
    x = range(len(items))
    fig, ax = plt.subplots(figsize=(8.6, 3.9))
    ax.bar(
        [i - 0.2 for i in x], before, width=0.38, color=C_MUTE, label="รอบ 1 (29 ส.ค.)"
    )
    ax.bar(
        [i + 0.2 for i in x], after, width=0.38, color=C_GOOD, label="รอบ 2 (1 ก.ย.)"
    )
    for i, (b, a) in enumerate(zip(before, after)):
        ax.text(i - 0.2, b + 0.04, "มี" if b else "ไม่มี", ha="center", fontsize=8.5)
        ax.text(i + 0.2, a + 0.04, "มี" if a else "ไม่มี", ha="center", fontsize=8.5)
    ax.set_xticks(list(x))
    ax.set_xticklabels(items, fontsize=8.5)
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["ไม่มี", "มี"])
    ax.set_ylim(0, 1.3)
    ax.legend(loc="upper left", fontsize=9)
    ax.set_title("รูปที่ 8  สิ่งที่เปลี่ยนจากชุดที่ส่งตรวจรอบแรก")
    save(fig, out, "fig08_coverage")


FIGS = [
    fig_decision_shift,
    fig_transitions,
    fig_map_score,
    fig_two_axes,
    fig_shap_saturation,
    fig_shap_example,
    fig_duplicate_ratio,
    fig_coverage,
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("docs/report_charts_l3"))
    args = ap.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    print(f"สร้างกราฟ {len(FIGS)} รูป -> {out}")
    for f in FIGS:
        f(out)
    print("เสร็จ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
