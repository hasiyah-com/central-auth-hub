"""สร้างกราฟทั้งหมดสำหรับรายงานผลการทดลอง RBA (.docx).

ตัวเลขทุกตัวคัดมาจากรายงานที่ freeze ไว้แล้ว (tag rba-expert-review-2026-08-29)
แต่ละชุดข้อมูลระบุไฟล์ต้นทางไว้ในตัวแปร SOURCE — ตรวจย้อนได้

    python ml-service/scripts/build_report_charts.py --out docs/report_charts

ไม่มี PII: ผู้ใช้อ้างด้วย alias เท่านั้น · ไม่มีอีเมล/ชื่อจริง/โฮสต์
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

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
C_MUTE = "#9E9E9E"

FIGS: list[tuple[str, str]] = []  # (ชื่อไฟล์, คำบรรยายสั้น)


def save(fig, out: Path, name: str, caption: str) -> None:
    p = out / f"{name}.png"
    fig.tight_layout()
    fig.savefig(p, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    FIGS.append((p.name, caption))
    print(f"  {p.name}")


def _bar_labels(ax, bars, fmt="{:.1f}%", dy=0.8):
    for b in bars:
        ax.text(
            b.get_x() + b.get_width() / 2,
            b.get_height() + dy,
            fmt.format(b.get_height()),
            ha="center",
            va="bottom",
            fontsize=9,
        )


# ═══════════════════════════════════════════════════════════════════════
# 1. Version sweep — จุดกระโดดอยู่ที่ไหน และทำไมมันเป็นภาพลวง
# ที่มา: tests/reports/v2_to_v7_version_sweep_2026-08-21.md
#        tests/reports/v7_generator_fix_2026-08-21.md
def fig_version_sweep(out: Path) -> None:
    ver = ["V4\nsequence", "V5\none-class IF", "V6\nsupervised RF", "V7\n= V6 (bundle)"]
    recall = [7.29, 8.65, 90.90, 90.90]
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    bars = ax.bar(ver, recall, color=[C_MUTE, C_L3, C_BAD, C_BAD], width=0.6)
    _bar_labels(ax, bars)
    ax.axhline(0.5, color=C_BAD, ls=":", lw=1.5)
    ax.annotate(
        "หลังแก้บั๊ก generator: 90.9% → ~0%",
        xy=(2.5, 0.5),
        xytext=(1.35, 42),
        fontsize=9.5,
        color=C_BAD,
        arrowprops=dict(arrowstyle="->", color=C_BAD, lw=1.4),
    )
    ax.set_ylabel("Event recall (%)")
    ax.set_ylim(0, 105)
    ax.set_title("รูปที่ 1  ผลการทดลองเลือกสถาปัตยกรรมโมเดล (V4–V7)")
    save(
        fig,
        out,
        "fig01_version_sweep",
        "recall ของโมเดลแต่ละเวอร์ชัน — จุดกระโดดที่ V6 เป็น artifact ไม่ใช่ความสามารถจริง",
    )


# 2. ทำไม 90.9% ถึงเป็นภาพลวง — one-sided shortcut
# ที่มา: v7_generator_fix_2026-08-21.md
def fig_shortcut(out: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    groups = ["ข้อมูล normal\n(ที่โมเดลเห็นตอนเทรน)", "ข้อมูล attack\n(ที่โมเดลเห็นตอนเทรน)"]
    vals = [0.0, 62.0]
    bars = ax.bar(groups, vals, color=[C_L1, C_BAD], width=0.45)
    _bar_labels(ax, bars, fmt="{:.0f}%")
    ax.set_ylabel("สัดส่วนแถวที่ success_10m > 0 (%)")
    ax.set_ylim(0, 80)
    ax.set_title("รูปที่ 2  สาเหตุของภาพลวง: ฟีเจอร์ที่ฝั่ง normal เป็น 0 เสมอ")
    ax.text(
        0.5,
        70,
        'โมเดลเรียน "ถ้า success_10m > 0 แปลว่า attack"\n'
        "ซึ่งเป็นกฎที่มีอยู่แค่ในข้อมูลจำลอง ไม่ใช่ในโลกจริง",
        ha="center",
        fontsize=9.5,
        color=C_BAD,
        bbox=dict(boxstyle="round,pad=0.4", fc="#FFEBEE", ec=C_BAD, lw=0.8),
    )
    save(
        fig,
        out,
        "fig02_generator_shortcut",
        "ฟีเจอร์ที่ฝั่ง normal ไม่เคยมีค่า ทำให้โมเดลเรียนทางลัดแทนพฤติกรรมจริง",
    )


# 3. Learning curve L1+L2 — ต้องมีข้อมูลกี่แถวถึงนิ่ง
# ที่มา: tests/reports/learning_curve_v2_2026-08-21.md
def fig_learning_curve_l12(out: Path) -> None:
    n = [10, 50, 100, 500, 1000]
    recall = [87.0, 88.9, 88.6, 88.8, 89.4]
    rerr = [1.0, 0.3, 0.7, 0.9, 0.2]
    fpr = [3.3, 1.2, 1.8, 1.7, 1.6]
    ferr = [1.7, 0.4, 0.9, 0.3, 0.3]
    fig, ax = plt.subplots(figsize=(7.4, 4.2))
    ax.errorbar(
        n, recall, yerr=rerr, marker="o", color=C_GOOD, lw=2, capsize=4, label="Recall"
    )
    ax.errorbar(
        n,
        fpr,
        yerr=ferr,
        marker="s",
        color=C_BAD,
        lw=2,
        capsize=4,
        label="Challenge FPR",
    )
    ax.set_xscale("log")
    ax.set_xticks(n)
    ax.set_xticklabels([str(x) for x in n])
    ax.axvline(50, color=C_MUTE, ls=":", lw=1.5)
    ax.text(52, 55, "จุดที่ FPR นิ่ง (~50 เหตุการณ์/คน)", fontsize=9, color="#555")
    ax.set_xlabel("จำนวนเหตุการณ์ที่ใช้สร้างโปรไฟล์ต่อผู้ใช้ 1 คน (log scale)")
    ax.set_ylabel("เปอร์เซ็นต์ (%)")
    ax.set_ylim(0, 100)
    ax.legend(loc="center right")
    ax.set_title("รูปที่ 3  Learning curve ของ L1+L2 (5 seeds, แถบ = CI95)")
    save(
        fig,
        out,
        "fig03_learning_curve_l12",
        "recall นิ่งตั้งแต่ 10 เหตุการณ์/คน · FPR นิ่งที่ ~50 · เกิน 100 ไม่ได้อะไรเพิ่ม",
    )


# 4. บั๊ก IForest sign กลับด้าน
# ที่มา: RBA_EXPERIMENTS_SUMMARY §4.1
def fig_sign_bug(out: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(8.0, 3.8), sharey=True)
    for ax, (title, atk, nrm, ok) in zip(
        axes,
        [
            ("ก่อนแก้ (ผิด)", 0.067, 0.097, False),
            ("หลังแก้ (ถูก)", 0.539, 0.454, True),
        ],
    ):
        bars = ax.bar(
            ["attack", "normal"],
            [atk, nrm],
            color=[C_BAD if not ok else C_GOOD, C_L1],
            width=0.5,
        )
        for b, v in zip(bars, [atk, nrm]):
            ax.text(
                b.get_x() + b.get_width() / 2,
                v + 0.012,
                f"{v:.3f}",
                ha="center",
                fontsize=9,
            )
        ax.set_title(
            title + ("   attack < normal", "   attack > normal")[ok],
            fontsize=10.5,
            color=C_BAD if not ok else C_GOOD,
        )
        ax.set_ylim(0, 0.65)
    axes[0].set_ylabel("ค่า anomaly เฉลี่ย")
    fig.suptitle(
        "รูปที่ 4  บั๊กเครื่องหมายของ IsolationForest — L3 ยิง 0/240 โดยไม่มีใครรู้",
        fontsize=12,
        fontweight="bold",
        y=1.02,
    )
    save(
        fig,
        out,
        "fig04_iforest_sign_bug",
        "ก่อนแก้ attack ได้คะแนนผิดปกติ *ต่ำกว่า* normal ทำให้ L3 ไม่เคยยิงเลย",
    )


# 5. สถิติรายคน vs neural network
# ที่มา: ablation_v8_vs_rule_2026-08-23.md · tier1_rarity_behavior_2026-08-25.md
def fig_stats_vs_nn(out: Path) -> None:
    labels = ["Phase 1\n(rule port)", "+ Tier 1\nสถิติรายคน", "V8\nTemporal MLP"]
    recall = [85.0, 95.8, 86.2]
    fpr = [2.11, 2.11, 14.1]
    x = range(len(labels))
    fig, ax = plt.subplots(figsize=(7.4, 4.2))
    b1 = ax.bar([i - 0.19 for i in x], recall, width=0.36, color=C_GOOD, label="Recall")
    b2 = ax.bar(
        [i + 0.19 for i in x], fpr, width=0.36, color=C_BAD, label="Challenge FPR"
    )
    _bar_labels(ax, b1)
    _bar_labels(ax, b2, fmt="{:.2f}%")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel("เปอร์เซ็นต์ (%)")
    ax.set_ylim(0, 110)
    ax.legend(loc="upper center", ncol=2)
    ax.annotate(
        "FPR สูงขึ้น 6.7 เท่า",
        xy=(2.19, 14.1),
        xytext=(1.5, 45),
        fontsize=9.5,
        color=C_BAD,
        arrowprops=dict(arrowstyle="->", color=C_BAD, lw=1.4),
    )
    ax.set_title("รูปที่ 5  สถิติรายคนเทียบกับ neural network (ชุดพัฒนา V2)")
    save(
        fig,
        out,
        "fig05_stats_vs_nn",
        "สถิติรายคนให้ recall สูงกว่า NN โดย FPR ไม่ขยับ ส่วน NN แลก recall ด้วย FPR ที่พุ่ง",
    )


# 6. พัฒนาการ recall ตลอดการทดลอง
# ที่มา: RBA_EXPERIMENTS_SUMMARY §10.3
def fig_progress(out: Path) -> None:
    steps = [
        "ก่อน Phase 1",
        "Phase 1\n(rule port)",
        "+ Tier 1\n(rarity)",
        "+ Tier 2\n(cadence)",
    ]
    recall = [25.0, 85.0, 95.8, 95.8]
    fig, ax = plt.subplots(figsize=(7.4, 4.0))
    ax.plot(steps, recall, marker="o", ms=9, lw=2.5, color=C_GOOD)
    for i, v in enumerate(recall):
        ax.annotate(
            f"{v:.1f}%",
            (i, v),
            textcoords="offset points",
            xytext=(0, 11),
            ha="center",
            fontsize=10,
            fontweight="bold",
        )
    ax.set_ylabel("Recall (%)")
    ax.set_ylim(0, 108)
    ax.set_title("รูปที่ 6  พัฒนาการของ recall ตลอดการทดลอง (ชุดพัฒนา V2)")
    ax.text(
        0.5,
        12,
        'การเพิ่มขึ้นทั้งหมดมาจาก "กฎ + สถิติ" ไม่ใช่จากโมเดล ML',
        fontsize=9.5,
        color="#555",
    )
    save(
        fig,
        out,
        "fig06_recall_progress",
        "recall เพิ่มจาก 25% เป็น 95.8% ด้วยกฎและสถิติล้วน · Tier 2 ไม่เพิ่ม recall แต่ปิดช่องทางเลี่ยง",
    )


# 7. FINAL GATE — ผลตามขนาดข้อมูล (ชุดที่โมเดลไม่เคยเห็น)
# ที่มา: tests/reports/exp_final_gate_2026-08-26.md §2
def fig_final_gate_size(out: Path) -> None:
    n = [50, 100, 500, 1000, 5000]
    recall = [63.3, 62.7, 61.7, 61.9, 61.9]
    rlo = [61.7, 61.0, 60.0, 60.2, 60.2]
    rhi = [65.0, 64.4, 63.4, 63.5, 63.6]
    prec = [53.0, 61.1, 69.0, 68.7, 69.1]
    plo = [51.4, 59.4, 67.3, 67.0, 67.4]
    phi = [54.6, 62.7, 70.7, 70.4, 70.7]
    cfpr = [3.0, 2.2, 1.5, 1.5, 1.5]
    l3fpr = [0.0, 0.9, 0.8, 0.8, 0.7]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.4, 4.2))
    ax1.errorbar(
        n,
        recall,
        yerr=[
            [a - b for a, b in zip(recall, rlo)],
            [b - a for a, b in zip(recall, rhi)],
        ],
        marker="o",
        lw=2,
        color=C_GOOD,
        capsize=4,
        label="Recall",
    )
    ax1.errorbar(
        n,
        prec,
        yerr=[[a - b for a, b in zip(prec, plo)], [b - a for a, b in zip(prec, phi)]],
        marker="s",
        lw=2,
        color=C_L4,
        capsize=4,
        label="Precision",
    )
    ax1.set_xscale("log")
    ax1.set_xticks(n)
    ax1.set_xticklabels([str(x) for x in n])
    ax1.set_ylim(40, 80)
    ax1.set_ylabel("เปอร์เซ็นต์ (%)")
    ax1.set_xlabel("เหตุการณ์ต่อผู้ใช้")
    ax1.legend()
    ax1.set_title("Recall / Precision")
    ax2.plot(n, cfpr, marker="o", lw=2, color=C_BAD, label="Challenge FPR")
    ax2.plot(n, l3fpr, marker="s", lw=2, color=C_L3, label="L3 FPR")
    ax2.axhline(1.0, color=C_MUTE, ls=":", lw=1.5)
    ax2.text(60, 1.08, "งบ L3 FPR ≤ 1%", fontsize=9, color="#555")
    ax2.set_xscale("log")
    ax2.set_xticks(n)
    ax2.set_xticklabels([str(x) for x in n])
    ax2.set_ylim(0, 3.6)
    ax2.set_xlabel("เหตุการณ์ต่อผู้ใช้")
    ax2.set_ylabel("อัตราแจ้งเตือนผิด (%)")
    ax2.legend()
    ax2.set_title("False positive")
    fig.suptitle(
        "รูปที่ 7  FINAL GATE — ชุดที่โมเดลไม่เคยเห็น (seeds 101–105, แถบ = Wilson CI95)",
        fontsize=12,
        fontweight="bold",
        y=1.03,
    )
    save(
        fig,
        out,
        "fig07_final_gate_by_size",
        "ผลบนชุดทดสอบใหม่ตามขนาดข้อมูลต่อคน — recall นิ่งราว 62% ส่วน precision ต้องการ ≥500 เหตุการณ์",
    )


# 8. FINAL GATE — แยกตามชั้น
# ที่มา: exp_final_gate_2026-08-26.md §3
def fig_layers(out: Path) -> None:
    labels = [
        "L1 Rule\n(เดี่ยว)",
        "L2 Behavior\n(เดี่ยว)",
        "L3 IForest\n(ยิงระดับ event)",
        "L4 รวม\n(challenge+)",
    ]
    vals = [50.5, 49.8, 5.7, 61.9]
    lo = [48.7, 48.0, 5.0, 60.2]
    hi = [52.2, 51.5, 6.6, 63.6]
    fig, ax = plt.subplots(figsize=(7.6, 4.2))
    bars = ax.bar(
        labels,
        vals,
        yerr=[[a - b for a, b in zip(vals, lo)], [b - a for a, b in zip(vals, hi)]],
        color=[C_L1, C_L2, C_L3, C_L4],
        width=0.6,
        capsize=5,
    )
    _bar_labels(ax, bars, dy=1.6)
    ax.set_ylabel("สัดส่วนเหตุการณ์โจมตีที่ตรวจพบ (%)")
    ax.set_ylim(0, 72)
    ax.set_title("รูปที่ 8  FINAL GATE — ความสามารถแยกตามชั้น (ข้อมูล 5,000 เหตุการณ์/คน)")
    save(
        fig,
        out,
        "fig08_layer_contribution",
        "L1 และ L2 ทำงานได้พอกัน (~50%) รวมกันเป็น 61.9% ส่วน L3 ยิงเพียง 5.7%",
    )


# 9. Campaign-level
# ที่มา: exp_final_gate_2026-08-26.md §4
def fig_campaign(out: Path) -> None:
    labels = ["L1/L2 มองเห็น", "L3 มองเห็น", "L3 เห็นคนเดียว"]
    vals = [96.7, 16.3, 0.7]
    lo = [94.0, 12.6, 0.2]
    hi = [98.2, 20.9, 2.4]
    fig, ax = plt.subplots(figsize=(7.4, 4.2))
    bars = ax.barh(
        labels,
        vals,
        xerr=[[a - b for a, b in zip(vals, lo)], [b - a for a, b in zip(vals, hi)]],
        color=[C_GOOD, C_L3, C_BAD],
        height=0.5,
        capsize=5,
    )
    for b, v in zip(bars, vals):
        ax.text(
            v + 2.2,
            b.get_y() + b.get_height() / 2,
            f"{v:.1f}%",
            va="center",
            fontsize=10,
            fontweight="bold",
        )
    ax.set_xlim(0, 110)
    ax.set_xlabel("สัดส่วนของแคมเปญโจมตี 300 ชุด (%)")
    ax.invert_yaxis()
    ax.set_title("รูปที่ 9  การตรวจจับระดับแคมเปญ (n = 300 แคมเปญ)")
    save(
        fig,
        out,
        "fig09_campaign_level",
        "L1/L2 มองเห็นแคมเปญเกือบทั้งหมด ส่วนที่ L3 เห็นอยู่คนเดียวมีเพียง 0.7%",
    )


# 10. Optimism bias — ชุดพัฒนา vs final gate
def fig_optimism(out: Path) -> None:
    metrics = ["Recall", "Precision"]
    dev = [95.8, 98.3]
    gate = [61.9, 69.1]
    x = range(len(metrics))
    fig, ax = plt.subplots(figsize=(6.8, 4.2))
    b1 = ax.bar(
        [i - 0.19 for i in x], dev, width=0.36, color=C_MUTE, label="ชุดพัฒนา (ใช้ปรับจูน)"
    )
    b2 = ax.bar(
        [i + 0.19 for i in x],
        gate,
        width=0.36,
        color=C_L4,
        label="FINAL GATE (ไม่เคยเห็น)",
    )
    _bar_labels(ax, b1)
    _bar_labels(ax, b2)
    for i in x:
        ax.annotate(
            "",
            xy=(i + 0.19, gate[i]),
            xytext=(i - 0.19, dev[i]),
            arrowprops=dict(arrowstyle="->", color=C_BAD, lw=1.6),
        )
        ax.text(
            i,
            (dev[i] + gate[i]) / 2,
            f"  −{dev[i] - gate[i]:.1f} จุด",
            color=C_BAD,
            fontsize=9.5,
            fontweight="bold",
        )
    ax.set_xticks(list(x))
    ax.set_xticklabels(metrics)
    ax.set_ylabel("เปอร์เซ็นต์ (%)")
    ax.set_ylim(0, 115)
    ax.legend(loc="upper right")
    ax.set_title("รูปที่ 10  ขนาดของ optimism bias ที่วัดได้")
    save(
        fig,
        out,
        "fig10_optimism_bias",
        "ส่วนต่างระหว่างชุดที่ใช้ปรับจูนกับชุดที่ไม่เคยเห็น — ตัวเลขชุดพัฒนาเป็นเพดานบน",
    )


# 11. Latency
# ที่มา: exp_final_gate_2026-08-26.md §5 + l3_stability_2026-08-29.md §2
def fig_latency(out: Path) -> None:
    n = [100, 500, 1000, 2000]
    fit = [111, 303, 154, 272]
    score = [1.36, 1.57, 1.44, 1.46]
    fig, ax = plt.subplots(figsize=(7.6, 4.2))
    b = ax.bar(
        [str(x) for x in n],
        fit,
        color=C_L3,
        width=0.5,
        label="เวลาเทรนโมเดลรายคน (fit)",
    )
    _bar_labels(ax, b, fmt="{:.0f} ms", dy=6)
    ax2 = ax.twinx()
    ax2.plot(
        [str(x) for x in n],
        score,
        marker="o",
        color=C_GOOD,
        lw=2.5,
        label="เวลาให้คะแนน 1 เหตุการณ์",
    )
    ax2.set_ylim(0, 6)
    ax2.set_ylabel("เวลาให้คะแนน (ms)", color=C_GOOD)
    ax2.grid(False)
    for i, v in enumerate(score):
        ax2.annotate(
            f"{v:.2f} ms",
            (i, v),
            textcoords="offset points",
            xytext=(0, 9),
            ha="center",
            fontsize=9,
            color=C_GOOD,
        )
    ax.set_ylim(0, 380)
    ax.set_ylabel("เวลาเทรน (ms)", color=C_L3)
    ax.set_xlabel("จำนวน residual ที่เก็บไว้ต่อผู้ใช้")
    ax.set_title("รูปที่ 11  ต้นทุนเวลาของ L3 — เทรนครั้งเดียวแล้วให้คะแนนได้เร็ว")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=9)
    save(
        fig,
        out,
        "fig11_latency",
        "การเทรนเกิดครั้งเดียวต่อชั่วโมงต่อคน ส่วนการให้คะแนนอยู่ระดับมิลลิวินาที",
    )


# 12. Tier reachability — ข้อจำกัดเชิงโครงสร้าง
# ที่มา: tests/reports/l3_shadow_replay_2026-08-29.md §5
def fig_reachability(out: Path) -> None:
    tiers = ["diagnostic\n(100 เหตุการณ์)", "warn\n(1,000)", "challenge\n(2,000)"]
    med_days = [61, 607, 1214]
    top_days = [11, 105, 210]
    x = range(len(tiers))
    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    b1 = ax.bar(
        [i - 0.19 for i in x],
        med_days,
        width=0.36,
        color=C_L3,
        label="ผู้ใช้ทั่วไป (1.65 ครั้ง/วัน)",
    )
    b2 = ax.bar(
        [i + 0.19 for i in x],
        top_days,
        width=0.36,
        color=C_L2,
        label="ผู้ใช้ที่ใช้งานมากที่สุด (9.51 ครั้ง/วัน)",
    )
    for bars in (b1, b2):
        for b in bars:
            ax.text(
                b.get_x() + b.get_width() / 2,
                b.get_height() * 1.06,
                f"{b.get_height():,.0f} วัน",
                ha="center",
                fontsize=8.5,
            )
    ax.axhline(365, color=C_BAD, ls="--", lw=1.6)
    ax.text(2.32, 400, "1 ปี", color=C_BAD, fontsize=9.5, ha="right")
    ax.set_yscale("log")
    ax.set_ylim(5, 4000)
    ax.set_xticks(list(x))
    ax.set_xticklabels(tiers)
    ax.set_ylabel("จำนวนวันที่ต้องใช้ (log scale)")
    ax.legend(loc="upper left", fontsize=9)
    ax.set_title("รูปที่ 12  เวลาที่ต้องใช้กว่า L3 จะเริ่มทำงาน (คำนวณจากอัตราการใช้งานจริง)")
    save(
        fig,
        out,
        "fig12_tier_reachability",
        "ระดับที่ L3 เริ่มขึ้นธงได้ต้องใช้เวลาราว 1.7 ปีสำหรับผู้ใช้ทั่วไป",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("docs/report_charts"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    print(f"สร้างกราฟลง {args.out}/")
    for fn in (
        fig_version_sweep,
        fig_shortcut,
        fig_learning_curve_l12,
        fig_sign_bug,
        fig_stats_vs_nn,
        fig_progress,
        fig_final_gate_size,
        fig_layers,
        fig_campaign,
        fig_optimism,
        fig_latency,
        fig_reachability,
    ):
        fn(args.out)
    print(f"\nรวม {len(FIGS)} รูป")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
