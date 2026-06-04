"""สร้างเอกสาร PDF อธิบาย 12 ML features + risk weight ต่อชั้น (Layer 1, 2, 3).

Output: docs/ml-12-features-risk-matrix.pdf

Run:   python scripts/gen_ml_features_doc.py
"""

from __future__ import annotations

from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ── Fonts ─────────────────────────────────────────────────────────────
# Tahoma มี glyph ไทยครบ — ทำงานบน Windows out-of-the-box.
TAHOMA = Path("C:/Windows/Fonts/tahoma.ttf")
TAHOMA_BOLD = Path("C:/Windows/Fonts/tahomabd.ttf")

if TAHOMA.exists():
    pdfmetrics.registerFont(TTFont("Tahoma", str(TAHOMA)))
    pdfmetrics.registerFont(TTFont("Tahoma-Bold", str(TAHOMA_BOLD)))
    FONT = "Tahoma"
    FONT_BOLD = "Tahoma-Bold"
else:
    FONT = "Helvetica"
    FONT_BOLD = "Helvetica-Bold"


# ── Styles ────────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

H1 = ParagraphStyle(
    "H1",
    parent=styles["Heading1"],
    fontName=FONT_BOLD,
    fontSize=18,
    textColor=colors.HexColor("#1e293b"),
    spaceAfter=8,
    spaceBefore=14,
)
H2 = ParagraphStyle(
    "H2",
    parent=styles["Heading2"],
    fontName=FONT_BOLD,
    fontSize=14,
    textColor=colors.HexColor("#334155"),
    spaceAfter=6,
    spaceBefore=12,
)
H3 = ParagraphStyle(
    "H3",
    parent=styles["Heading3"],
    fontName=FONT_BOLD,
    fontSize=11,
    textColor=colors.HexColor("#475569"),
    spaceAfter=4,
    spaceBefore=8,
)
BODY = ParagraphStyle(
    "Body",
    parent=styles["BodyText"],
    fontName=FONT,
    fontSize=10,
    leading=14,
    textColor=colors.HexColor("#1f2937"),
    spaceAfter=4,
)
SMALL = ParagraphStyle(
    "Small",
    parent=BODY,
    fontSize=8.5,
    leading=11,
    textColor=colors.HexColor("#475569"),
)
MONO = ParagraphStyle(
    "Mono",
    parent=BODY,
    fontName=FONT,
    fontSize=9,
    leading=12,
    textColor=colors.HexColor("#0f172a"),
    backColor=colors.HexColor("#f1f5f9"),
    leftIndent=8,
    rightIndent=8,
    spaceBefore=4,
    spaceAfter=8,
)
COVER_TITLE = ParagraphStyle(
    "CoverTitle",
    parent=H1,
    fontSize=24,
    alignment=1,
    spaceAfter=20,
)
COVER_SUB = ParagraphStyle(
    "CoverSub",
    parent=BODY,
    fontSize=12,
    alignment=1,
    textColor=colors.HexColor("#64748b"),
    spaceAfter=4,
)

CELL = ParagraphStyle(
    "Cell",
    parent=BODY,
    fontName=FONT,
    fontSize=8.5,
    leading=10,
)
CELL_BOLD = ParagraphStyle(
    "CellBold",
    parent=CELL,
    fontName=FONT_BOLD,
)


def P(text: str, style=BODY) -> Paragraph:
    return Paragraph(text, style)


# ── Data: The 12 features (single source of truth) ────────────────────
FEATURES = [
    {
        "n": 1,
        "name": "hour_of_day",
        "category": "Temporal",
        "range": "0–23",
        "what": "ชั่วโมงของวันที่ user login (UTC) — 0=เที่ยงคืน, 14=บ่าย 2",
        "why": "Attacker มักทำงานนอกเวลาที่เจ้าของบัญชีใช้ปกติ (เช่น ตี 3) — feature นี้คู่กับ behavior profile (feature #4)",
        "l1": "—",
        "l2": "indirect (compute typical_hour)",
        "l3": "✓",
        "citation": "Wiefling 2022",
    },
    {
        "n": 2,
        "name": "day_of_week",
        "category": "Temporal",
        "range": "0–6 (Mon–Sun)",
        "what": "วันในสัปดาห์ที่ login — 0=จันทร์, 6=อาทิตย์",
        "why": "ใช้คู่กับ is_weekend ตรวจ pattern เช่น admin ที่ปกติเข้าจ-ศ แล้วโผล่มาอาทิตย์เช้า",
        "l1": "—",
        "l2": "indirect (weekend pattern)",
        "l3": "✓",
        "citation": "Wiefling 2020",
    },
    {
        "n": 3,
        "name": "is_weekend",
        "category": "Temporal",
        "range": "0/1",
        "what": "เป็นวันหยุดเสาร์-อาทิตย์ไหม — 1=ใช่",
        "why": "เทียบกับ typical_weekend ของ user (จาก 30-day profile) — mismatch = สงสัย",
        "l1": "—",
        "l2": "+0.10 ถ้า mismatch",
        "l3": "✓",
        "citation": "Wiefling 2022",
    },
    {
        "n": 4,
        "name": "hours_from_typical_login_time",
        "category": "Temporal (personalized)",
        "range": "0–12",
        "what": "ห่างจากเวลาที่ user ปกติ login กี่ชั่วโมง — คำนวณจาก mode ของ hour_of_day ใน 30 วัน",
        "why": "ห่าง 8-10 ชม. = user ที่ปกติทำงานเช้าโผล่มาตอน 2 ทุ่ม — สัญญาณ takeover แรงมาก. "
        "Cold start: ถ้า user มี history &lt; 5 sessions ใช้ค่า neutral (0.0)",
        "l1": "—",
        "l2": "<b>+0.40</b> (≥10h) / +0.20 (≥6h)",
        "l3": "✓",
        "citation": "Wiefling 2022 (Sec 5.2)",
    },
    {
        "n": 5,
        "name": "is_thailand",
        "category": "Geographic",
        "range": "0/1",
        "what": "Login จากไอพีที่ MaxMind GeoIP แมปเป็น TH ไหม — 1=ใช่",
        "why": "Hub ของมหา'ลัยคาดว่า user ส่วนใหญ่อยู่ในไทย — login นอกประเทศ = score เพิ่ม +0.10",
        "l1": "+0.10 ถ้า =0",
        "l2": "—",
        "l3": "✓",
        "citation": "Wiefling 2022",
    },
    {
        "n": 6,
        "name": "is_new_country",
        "category": "Geographic",
        "range": "0/1",
        "what": "ประเทศที่ login ครั้งนี้ เคยอยู่ใน history 30 วันของ user ไหม — 0=เคย, 1=ใหม่",
        "why": "Feature ที่มี <b>weight สูงสุดร่วม</b>: Layer 1 + Layer 2 รวมกัน +0.60 — "
        "ประเทศใหม่เป็นสัญญาณ phishing หรือ credential leak ที่ชัดเจน",
        "l1": "<b>+0.30</b>",
        "l2": "<b>+0.30</b>",
        "l3": "✓",
        "citation": "Freeman 2016 / Wiefling 2022",
    },
    {
        "n": 7,
        "name": "country_change_count_30d",
        "category": "Geographic",
        "range": "0–10+",
        "what": "นับจำนวนครั้งที่ user เปลี่ยนประเทศใน 30 วันล่าสุด",
        "why": "นับ ≥ 8 = <b>HARD BLOCK ทันที</b> — pattern ของ botnet หรือ proxy hopping. "
        "Normal user 0-2 ครั้งต่อเดือนเท่านั้น",
        "l1": "<b>HARD BLOCK ≥ 8</b>",
        "l2": "—",
        "l3": "✓",
        "citation": "Wiefling 2022 (country churn)",
    },
    {
        "n": 8,
        "name": "is_new_device",
        "category": "Device",
        "range": "0/1",
        "what": "Device fingerprint (User-Agent + browser family hash) เคยปรากฏใน history ไหม",
        "why": "Weight รวมสูง (+0.50) — Layer 1 +0.30 (rule), Layer 2 +0.20 (behavior). "
        "Combine กับ is_new_country → 99% เป็น takeover",
        "l1": "<b>+0.30</b>",
        "l2": "+0.20",
        "l3": "✓",
        "citation": "Laperdrix 2020",
    },
    {
        "n": 9,
        "name": "is_new_user_agent_family",
        "category": "Device",
        "range": "0/1",
        "what": "Browser family (Chrome, Safari, Firefox) เคยใช้ไหม — ละเอียดน้อยกว่า is_new_device แต่ผันได้ยากกว่า",
        "why": "User-Agent string สามารถ spoof ได้ง่าย แต่การเปลี่ยน browser family บอกได้ว่ามีการเปลี่ยน OS หรือ device",
        "l1": "+0.20",
        "l2": "—",
        "l3": "✓",
        "citation": "Laperdrix 2020 / Iqbal 2021",
    },
    {
        "n": 10,
        "name": "log_minutes_since_last_login",
        "category": "Velocity",
        "range": "0–10+ (log scale)",
        "what": "Log ของเวลาเป็นนาทีตั้งแต่ user login ครั้งก่อน — log10(minutes + 1)",
        "why": "ค่าต่ำมาก (เช่น 0.5 = 2 นาทีก่อน) อาจเป็น session hijack ที่ใช้ token จากเครื่องที่ถูกขโมย "
        "ใช้ log scale เพราะ raw minutes กระจายเป็น power law",
        "l1": "—",
        "l2": "—",
        "l3": "✓ (only)",
        "citation": "Microsoft Entra ID Protection",
    },
    {
        "n": 11,
        "name": "login_count_24h",
        "category": "Velocity",
        "range": "0–100+",
        "what": "จำนวน login สำเร็จของ user ใน 24 ชม. ที่ผ่านมา",
        "why": "นับ ≥ 50 = HARD BLOCK — pattern ของ credential stuffing หรือ automation. "
        "Normal user 1-5 ครั้งต่อวัน",
        "l1": "<b>HARD BLOCK ≥ 50</b>",
        "l2": "—",
        "l3": "✓",
        "citation": "OWASP API4:2023",
    },
    {
        "n": 12,
        "name": "failed_logins_24h",
        "category": "Brute Force",
        "range": "0–10+",
        "what": "จำนวน login ล้มเหลวของ user ใน 24 ชม. (account ถูก challenge แล้วเข้าไม่ได้)",
        "why": "≥ 3 = score +0.20 (suspicious). ≥ 10 = HARD BLOCK (brute force). "
        "NIST SP 800-63B-4 แนะนำให้ rate-limit ที่ตัวเลขนี้",
        "l1": "+0.20 (≥3), <b>BLOCK ≥ 10</b>",
        "l2": "—",
        "l3": "✓",
        "citation": "NIST SP 800-63B-4",
    },
]


# ── Document build ────────────────────────────────────────────────────
def build():
    out = Path("docs/ml-12-features-risk-matrix.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="ML 12 Features — Risk Weight Matrix",
        author="Central Auth Hub",
    )

    story: list = []

    # ─── Cover ───
    story.append(Spacer(1, 4 * cm))
    story.append(P("ML 12 Features<br/>Risk Weight Matrix", COVER_TITLE))
    story.append(Spacer(1, 0.6 * cm))
    story.append(P("Central Auth Hub — Hybrid RBA 4-Layer", COVER_SUB))
    story.append(Spacer(1, 0.3 * cm))
    story.append(
        P(
            "คู่มืออธิบาย 12 features ของ Isolation Forest ที่ใช้ใน Layer 3<br/>"
            "พร้อม risk weight ของแต่ละ feature ใน Layer 1 (Rule) และ Layer 2 (Behavior)",
            COVER_SUB,
        )
    )
    story.append(Spacer(1, 5 * cm))
    story.append(
        P(
            "จัดทำจาก code จริงที่ commit ใน <b>main</b> branch:<br/>"
            "<font name='Tahoma' size='9' color='#475569'>"
            "hub/backend/app/security/rule_engine.py, "
            "behavior_profiling.py, iforest_scorer.py, "
            "ml-service/app/features.py</font>",
            COVER_SUB,
        )
    )

    story.append(PageBreak())

    # ─── 1. Overview ───
    story.append(P("1. ภาพรวม 4-Layer RBA", H1))
    story.append(
        P(
            "ระบบใช้ Hybrid Risk-Based Authentication 4 ชั้น (อ้างอิง Freeman 2016, "
            "Wiefling 2022, F-RBA 2024) — ทุก login ผ่าน 4 ขั้นตอนนี้:",
            BODY,
        )
    )
    arch = [
        ["Layer", "ชื่อ", "ทำอะไร", "Output"],
        [
            "1",
            "Rule Engine",
            "เช็คกฎตายตัว: brute force, impossible travel, IP blacklist, new device/country",
            "score 0.0-1.0, blocked: bool, reasons[]",
        ],
        [
            "2",
            "Behavior Profiling",
            "เทียบ features ปัจจุบันกับ baseline 30 วันของ user (cold start ถ้า history &lt; 5)",
            "score 0.0-1.0, reasons[]",
        ],
        [
            "3",
            "Isolation Forest",
            "ML unsupervised — ใช้ 12 features ทั้งหมด คืน anomaly score + SHAP top-5",
            "raw 0.0-1.0 → risk 0.0-0.4, explanation[]",
        ],
        [
            "4",
            "Risk Aggregation",
            "รวม score จาก 3 ชั้น → final decision",
            "block / challenge / warn / allow",
        ],
    ]
    arch_tbl = Table(
        [
            [P(c, CELL_BOLD) if i == 0 else P(c, CELL) for c in row]
            for i, row in enumerate(arch)
        ],
        colWidths=[1.2 * cm, 3.5 * cm, 7.5 * cm, 5 * cm],
    )
    arch_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#f8fafc")],
                ),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(arch_tbl)
    story.append(Spacer(1, 0.4 * cm))
    story.append(
        P(
            "Decision thresholds (Layer 4): "
            "<b>block ≥ 0.8</b>, <b>challenge ≥ 0.5</b>, <b>warn ≥ 0.3</b>, allow &lt; 0.3 ",
            SMALL,
        )
    )

    # ─── 2. Risk Weight Matrix (summary table) ───
    story.append(P("2. Risk Weight Matrix — สรุปต่อ feature", H1))
    story.append(
        P(
            "ตารางสรุปว่า <b>แต่ละ feature ถูก score ที่ Layer ไหนบ้าง และ weight เท่าไร</b> "
            "— อ่านเพื่อรู้ว่า feature ตัวไหนเสี่ยงสูง/ต่ำ:",
            BODY,
        )
    )

    matrix_header = [
        "#",
        "Feature",
        "Layer 1<br/>(Rule)",
        "Layer 2<br/>(Behavior)",
        "Layer 3<br/>(IForest)",
    ]
    matrix_rows = [[P(c, CELL_BOLD) for c in matrix_header]]
    for f in FEATURES:
        max_per = []
        for col in ["l1", "l2"]:
            v = f[col]
            if "HARD BLOCK" in v or "BLOCK" in v:
                max_per.append("hard")
            elif "+0.4" in v:
                max_per.append("high")
            elif "+0.3" in v:
                max_per.append("high")
            elif "+0.2" in v:
                max_per.append("med")
            elif "+0.1" in v:
                max_per.append("low")
        matrix_rows.append(
            [
                P(str(f["n"]), CELL),
                P(
                    f"<font name='{FONT_BOLD}'>{f['name']}</font><br/>"
                    f"<font color='#64748b' size='7'>{f['category']}</font>",
                    CELL,
                ),
                P(f["l1"], CELL),
                P(f["l2"], CELL),
                P(f["l3"], CELL),
            ]
        )
    matrix_tbl = Table(
        matrix_rows, colWidths=[0.8 * cm, 5 * cm, 4 * cm, 4.5 * cm, 2.7 * cm]
    )
    matrix_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#f8fafc")],
                ),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(matrix_tbl)

    story.append(Spacer(1, 0.4 * cm))
    story.append(
        P(
            "<b>High-risk features (rank by max total weight):</b><br/>"
            "🔥 <b>is_new_country</b> (max 0.60) — Layer 1 + 2 score รวม<br/>"
            "🔥 <b>is_new_device</b> (max 0.50) — Layer 1 + 2 รวม<br/>"
            "🔥 <b>hours_from_typical_login_time</b> (max 0.40 — Layer 2 เท่านั้น)<br/>"
            "☠️ <b>HARD BLOCK triggers:</b> country_change_count_30d ≥ 8, "
            "login_count_24h ≥ 50, failed_logins_24h ≥ 10, IP blacklist, impossible travel",
            BODY,
        )
    )

    story.append(PageBreak())

    # ─── 3. Per-feature detail ───
    story.append(P("3. รายละเอียดต่อ feature", H1))
    story.append(
        P(
            "แต่ละ feature อธิบาย: ทำอะไร, ทำไมเสี่ยง, weight ที่แต่ละ layer, "
            "และ research paper อ้างอิง",
            BODY,
        )
    )

    for f in FEATURES:
        # Feature header
        story.append(
            P(
                f"#{f['n']}. <font name='{FONT_BOLD}'>{f['name']}</font> "
                f"<font color='#64748b' size='9'>· {f['category']} · "
                f"range {f['range']}</font>",
                H2,
            )
        )
        # What it does
        story.append(P(f"<b>คืออะไร:</b> {f['what']}", BODY))
        # Why it's risky
        story.append(P(f"<b>เสี่ยงตรงไหน:</b> {f['why']}", BODY))
        # Weight table per layer
        wt = Table(
            [
                [P("<b>Layer 1 (Rule)</b>", CELL), P(f["l1"], CELL)],
                [P("<b>Layer 2 (Behavior)</b>", CELL), P(f["l2"], CELL)],
                [P("<b>Layer 3 (IForest)</b>", CELL), P(f["l3"], CELL)],
                [P("<b>Citation</b>", CELL), P(f["citation"], CELL)],
            ],
            colWidths=[4 * cm, 12.5 * cm],
        )
        wt.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(wt)
        story.append(Spacer(1, 0.3 * cm))

    story.append(PageBreak())

    # ─── 4. Special rules (not feature-based) ───
    story.append(P("4. กฎเสริม (ไม่ผูก feature ตรงๆ)", H1))
    story.append(
        P(
            "นอกจาก 12 features Layer 1 ยังเช็คกฎ <b>cross-cutting</b> เพิ่มเติม "
            "ที่ใช้ context (IP, geo) มากกว่าค่า feature เดี่ยว:",
            BODY,
        )
    )

    cross = [
        ["กฎ", "Trigger", "ผลลัพธ์"],
        ["IP Blacklist", "IP อยู่ใน blacklist table", "HARD BLOCK"],
        [
            "Impossible Travel",
            "user เปลี่ยนประเทศ &lt; 1 ชม. (เช่น TH → US in 0.5h)",
            "HARD BLOCK",
        ],
        [
            "Multi-account IP",
            "> 5 distinct user_id จาก IP เดียวกันใน 1 ชม.",
            "score +0.25",
        ],
    ]
    cross_tbl = Table(
        [
            [P(c, CELL_BOLD) if i == 0 else P(c, CELL) for c in row]
            for i, row in enumerate(cross)
        ],
        colWidths=[4 * cm, 8.5 * cm, 4.5 * cm],
    )
    cross_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(cross_tbl)

    # ─── 5. SHAP for Layer 3 ───
    story.append(P("5. Layer 3 — SHAP Explainability", H1))
    story.append(
        P(
            "Layer 3 (Isolation Forest) ใช้ <b>ทั้ง 12 features รวมกัน</b> เพื่อคำนวณ anomaly score. "
            "แต่ score ตัวเดียวไม่บอกว่า feature ไหน contribute เท่าไร — เราใช้ "
            "<b>SHAP TreeExplainer</b> (Lundberg & Lee 2017) ให้ค่า per-feature contribution:",
            BODY,
        )
    )

    story.append(P("Output ที่ ml-service คืน (ตัวอย่าง anomalous login):", H3))
    story.append(
        P(
            "<font name='Tahoma'>"
            "{<br/>"
            '&nbsp;&nbsp;"anomaly_score": 0.7034,<br/>'
            '&nbsp;&nbsp;"decision": "block",<br/>'
            '&nbsp;&nbsp;"explanation": [<br/>'
            '&nbsp;&nbsp;&nbsp;&nbsp;{"feature": "country_change_count_30d", "shap": 1.58, "direction": "anomaly"},<br/>'
            '&nbsp;&nbsp;&nbsp;&nbsp;{"feature": "failed_logins_24h",        "shap": 1.58, "direction": "anomaly"},<br/>'
            '&nbsp;&nbsp;&nbsp;&nbsp;{"feature": "is_new_device",            "shap": 1.36, "direction": "anomaly"},<br/>'
            '&nbsp;&nbsp;&nbsp;&nbsp;{"feature": "is_new_user_agent_family", "shap": 1.12, "direction": "anomaly"},<br/>'
            '&nbsp;&nbsp;&nbsp;&nbsp;{"feature": "hours_from_typical_login_time", "shap": 0.85, "direction": "anomaly"}<br/>'
            "&nbsp;&nbsp;]<br/>"
            "}"
            "</font>",
            MONO,
        )
    )

    story.append(P("Sign convention (สำคัญ):", H3))
    story.append(
        P(
            "• <b>shap &gt; 0</b> (positive) → feature ผลัก score ไปทาง <b>anomaly</b> (🔴 แดงใน UI)<br/>"
            "• <b>shap &lt; 0</b> (negative) → feature ผลักไปทาง <b>normal</b> (🟢 เขียวใน UI)<br/>"
            "• Top-5 features เรียงตาม <b>|shap|</b> (absolute value)<br/>"
            "• Fail-safe: ถ้า SHAP error → คืน explanation=[] ระบบทำงานต่อได้",
            BODY,
        )
    )

    story.append(P("ดูใน UI ที่ไหน:", H3))
    story.append(
        P(
            "Admin Dashboard → /admin/ml → คลิก session → SessionDetailPanel:<br/>"
            "• <b>Risk Score header</b> + 4-Layer breakdown bars<br/>"
            "• <b>Reasons (Layer 1 + 2)</b> — bars สีแดง พร้อม weight<br/>"
            "• <b>SHAP (Layer 3 · IForest)</b> — bars สี (🔴 anomaly / 🟢 normal)",
            BODY,
        )
    )

    story.append(PageBreak())

    # ─── 6. Risk Score interpretation ───
    story.append(P("6. การตีความ Risk Score", H1))
    story.append(P("Layer 4 รวม score จาก 3 ชั้น แล้วแมปเป็น decision:", BODY))

    decision_tbl = Table(
        [
            [
                P("<b>Decision</b>", CELL_BOLD),
                P("<b>Score</b>", CELL_BOLD),
                P("<b>ระบบทำอะไร</b>", CELL_BOLD),
            ],
            [
                P("allow", CELL),
                P("&lt; 0.3", CELL),
                P("ผ่านปกติ — ออก JWT ใช้งานเต็มสิทธิ์", CELL),
            ],
            [
                P("<font color='#92400e'>warn</font>", CELL),
                P("0.3 - 0.49", CELL),
                P("ผ่าน + log warning + audit metadata มี iforest_explanation", CELL),
            ],
            [
                P("<font color='#b45309'>challenge</font>", CELL),
                P("0.5 - 0.79", CELL),
                P(
                    "ออก JWT แบบ <b>restricted=true</b> (Path B Session Downgrade — รอ implement)",
                    CELL,
                ),
            ],
            [
                P("<font color='#dc2626'>block</font>", CELL),
                P("≥ 0.8", CELL),
                P("403 Forbidden + audit + alert admin", CELL),
            ],
        ],
        colWidths=[3 * cm, 3 * cm, 11 * cm],
    )
    decision_tbl.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#f8fafc")],
                ),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(decision_tbl)

    story.append(Spacer(1, 0.4 * cm))
    story.append(
        P(
            "<b>Shadow Mode (ปัจจุบัน):</b> ตั้ง <font name='Tahoma'>ML_SHADOW_MODE=true</font> "
            "ใน .env → block/challenge/warn ถูกเปลี่ยนเป็น "
            "would_block/would_challenge/would_warn ตามลำดับ (log แต่ไม่บังคับ) — "
            "ใช้สำหรับเก็บข้อมูล + ปรับ threshold ก่อนเปิด enforcement จริง",
            SMALL,
        )
    )

    # ─── 7. References ───
    story.append(P("7. อ้างอิงงานวิจัย", H1))
    refs = [
        (
            "Liu, Ting, Zhou (2008)",
            "Isolation Forest — ICDM 2008. อัลกอริทึมหลักของ Layer 3.",
        ),
        (
            "Freeman et al. (2016)",
            "Who Are You? A Statistical Approach to Measuring User Authenticity. "
            "Risk scoring weights สำหรับ new device/country.",
        ),
        (
            "Wiefling et al. (2020, 2022)",
            "Pump Up Password Security! / More Than Just Good Passwords? "
            "ACM TOPS. Temporal + behavior pattern, RBA effectiveness study.",
        ),
        (
            "Lundberg & Lee (2017)",
            "A Unified Approach to Interpreting Model Predictions — NeurIPS. SHAP framework.",
        ),
        (
            "Laperdrix et al. (2020)",
            "Browser Fingerprinting Survey. Device fingerprint pitfalls.",
        ),
        (
            "F-RBA (2024)",
            "Federated Risk-Based Authentication. Multi-layer architecture pattern.",
        ),
        (
            "NIST SP 800-63B-4 (2024 draft)",
            "Digital Identity Guidelines. Failed-login threshold (10), MFA out-of-band.",
        ),
        (
            "OWASP API Security Top 10 (2023)",
            "API4 — Unrestricted Resource Consumption (credential stuffing).",
        ),
        (
            "Microsoft Entra ID Protection (2024)",
            "Impossible travel + velocity feature definitions.",
        ),
    ]
    for src, desc in refs:
        story.append(P(f"<b>{src}</b> — {desc}", BODY))

    # Build
    doc.build(story)
    print(f"✓ Generated {out} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    build()
