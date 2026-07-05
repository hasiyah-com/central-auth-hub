/* สร้างรายงานรวม .docx (dataset + model comparison + ablation + SHAP + robustness + decision)
 * ฝังรูปทั้งหมดจาก hub/backend/tests/reports/figures/
 * Run: NODE_PATH="$(npm root -g)" node ml-service/scripts/build_report_docx.js
 */
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  ImageRun, AlignmentType, HeadingLevel, BorderStyle, WidthType, ShadingType,
  TableOfContents, PageBreak, LevelFormat, Footer, PageNumber,
} = require("docx");

const ROOT = path.resolve(__dirname, "..", "..");
const FIG = path.join(ROOT, "hub", "backend", "tests", "reports", "figures");
const OUT = process.argv[2] || path.join(ROOT, "hub", "backend", "tests", "reports", "Benchmark_RBA_Report_2026-06-15.docx");
const FONT = "Tahoma";
const CW = 9360; // content width US Letter, 1" margins

// ---------- helpers ----------
function pngSize(p) { const b = fs.readFileSync(p); return { w: b.readUInt32BE(16), h: b.readUInt32BE(20) }; }
function image(rel, targetW) {
  const p = path.join(FIG, rel); const { w, h } = pngSize(p);
  return new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120, after: 60 },
    children: [new ImageRun({ type: "png", data: fs.readFileSync(p),
      transformation: { width: targetW, height: Math.round(targetW * h / w) },
      altText: { title: "figure", description: rel, name: rel } })] });
}
function cap(t) { return new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 160 },
  children: [new TextRun({ text: t, italics: true, size: 18, color: "555555" })] }); }
function h1(t) { return new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)] }); }
function h2(t) { return new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] }); }
function p(t, opts = {}) { return new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text: t, ...opts })] }); }
function bullet(t) { return new Paragraph({ numbering: { reference: "b", level: 0 }, spacing: { after: 60 },
  children: [new TextRun(t)] }); }

const border = { style: BorderStyle.SINGLE, size: 1, color: "BBBBBB" };
const borders = { top: border, bottom: border, left: border, right: border,
  insideHorizontal: border, insideVertical: border };
function cell(text, w, { head = false, bold = false, fill = null, align = AlignmentType.LEFT } = {}) {
  return new TableCell({ width: { size: w, type: WidthType.DXA },
    shading: fill ? { fill, type: ShadingType.CLEAR } : (head ? { fill: "2E5A88", type: ShadingType.CLEAR } : undefined),
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: [new Paragraph({ alignment: align, children: [new TextRun({ text: String(text),
      bold: head || bold, color: head ? "FFFFFF" : "000000", size: 18 })] })] });
}
function table(headRow, rows, widths) {
  const trs = [new TableRow({ tableHeader: true, children: headRow.map((t, i) =>
    cell(t, widths[i], { head: true, align: i === 0 ? AlignmentType.LEFT : AlignmentType.CENTER })) })];
  for (const r of rows) {
    trs.push(new TableRow({ children: r.map((c, i) => {
      const o = (c && typeof c === "object") ? c : { v: c };
      return cell(o.v, widths[i], { bold: o.bold, fill: o.fill,
        align: i === 0 ? AlignmentType.LEFT : AlignmentType.CENTER });
    }) }));
  }
  return new Table({ width: { size: CW, type: WidthType.DXA }, columnWidths: widths, borders, rows: trs });
}
// two images side by side (borderless table)
function sideBySide(relL, relR, w) {
  const noB = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
  const nb = { top: noB, bottom: noB, left: noB, right: noB, insideHorizontal: noB, insideVertical: noB };
  const mk = (rel) => new TableCell({ width: { size: CW / 2, type: WidthType.DXA }, borders: nb,
    children: [image(rel, w)] });
  return new Table({ width: { size: CW, type: WidthType.DXA }, columnWidths: [CW / 2, CW / 2], borders: nb,
    rows: [new TableRow({ children: [mk(relL), mk(relR)] })] });
}
const HL = "F4D03F"; // highlight winner

// ---------- content ----------
const kids = [];

// Title page
kids.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 2600, after: 120 },
  children: [new TextRun({ text: "รายงานการทดลอง", bold: true, size: 52 })] }));
kids.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 80 },
  children: [new TextRun({ text: "Hybrid RBA + Passkey Trust Layer", bold: true, size: 40, color: "2E5A88" })] }));
kids.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 },
  children: [new TextRun({ text: "การสร้าง Dataset และเปรียบเทียบโมเดล Unsupervised", size: 28 })] }));
kids.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 400 },
  children: [new TextRun({ text: "บนฐาน RBA Dataset (Wiefling et al. 2022)", size: 24, italics: true, color: "555555" })] }));
kids.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 40 },
  children: [new TextRun({ text: "Central Auth Hub — Senior Project", size: 24 })] }));
kids.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 40 },
  children: [new TextRun({ text: "ผู้จัดทำ: hasiyahdama5@gmail.com", size: 22 })] }));
kids.push(new Paragraph({ alignment: AlignmentType.CENTER,
  children: [new TextRun({ text: "วันที่ 15 มิถุนายน 2026", size: 22 })] }));
kids.push(new Paragraph({ children: [new PageBreak()] }));

// TOC
kids.push(new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("สารบัญ")] }));
kids.push(new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-2" }));
kids.push(new Paragraph({ spacing: { after: 60 }, children: [new TextRun({ text: "(เปิดใน Word แล้วกด F9 เพื่ออัปเดตเลขหน้า)", italics: true, size: 16, color: "888888" })] }));
kids.push(new Paragraph({ children: [new PageBreak()] }));

// Overview — ML workflow 7 steps
kids.push(h1("ภาพรวมกระบวนการ ML (7 ขั้นตอน)"));
kids.push(p("งานทั้งหมดในรายงานนี้จัดตามกระบวนการ Machine Learning มาตรฐาน 7 ขั้น (รายละเอียดแต่ละขั้นอยู่ในบทถัดไป)"));
kids.push(table(["ขั้นตอน", "สิ่งที่ทำในโปรเจค"], [
  ["1. กำหนดเป้าหมายและปัญหา", "ตรวจจับ Account Takeover แบบ unsupervised (imbalanced) → metric หลัก PR-AUC; ต้อง explainable + real-time"],
  ["2. รวบรวมข้อมูล", "RBA dataset จริง 31.3M (sample 10,000 normal + ATO จริง 100–141) + synthetic 40 แถว → 2 ชุด (semi-synthetic / real-only)"],
  ["3. เตรียมและทำความสะอาดข้อมูล", "filter normal สะอาด, True/False→1/0, parse timestamp+UA, ตัด missing/รก, cap login/user, cold-start = neutral"],
  ["4. เลือกและสร้างฟีเจอร์", "23 features (Experiment A/B/C) และ 12 features (real-only), is_thailand proxy, StandardScaler, SHAP-guided"],
  ["5. เลือกอัลกอริทึมและฝึกสอนโมเดล", "IsolationForest / OneClassSVM / LocalOutlierFactor × 2 โปรโตคอล (in-sample + proper one-class group-by-user)"],
  ["6. ประเมินโมเดล", "Precision/Recall/F1/ROC-AUC/PR-AUC + ablation + robustness (Wilcoxon) + real-vs-synthetic + SHAP"],
  ["7. นำไปใช้งานจริง", "เลือก IsolationForest (explainable+เร็ว+เสถียร) + Shadow Mode + 4-layer RBA (/v1/score) + retrain workflow"],
], [3200, 6160]));
kids.push(cap("ตารางภาพรวม — mapping งานทั้งหมดเข้ากับ ML lifecycle 7 ขั้น"));

// --- รายละเอียดแต่ละขั้น ---
kids.push(h2("ขั้นที่ 1 — กำหนดเป้าหมายและปัญหา"));
kids.push(table(["หัวข้อ", "รายละเอียด"], [
  ["ปัญหา", "ตรวจจับ Account Takeover (ATO) / login ผิดปกติ ในระบบ Central Auth Hub แบบ Risk-Based Authentication"],
  ["ชนิดปัญหา", "Unsupervised anomaly detection — ตอนใช้จริงไม่มี label, attack หายากมาก (imbalanced ~1.4%)"],
  ["คำถามวิจัย", "(1) feature engineering เพิ่มการตรวจ ATO ได้ไหม (2) Passkey Trust Layer ลด False Positive ได้ไหม (3) โมเดลไหนเหมาะสุด (4) ใช้จริงใน Hub ได้ไหม"],
  ["ตัวชี้วัดหลัก", "PR-AUC (เหมาะ imbalanced) + ROC-AUC, Precision/Recall/F1"],
  ["ข้อจำกัดออกแบบ", "ต้อง real-time + อธิบาย decision ได้ (audit) → explainability เป็น requirement"],
], [2200, 7160]));

kids.push(h2("ขั้นที่ 2 — รวบรวมข้อมูล"));
kids.push(table(["แหล่ง", "รายละเอียด"], [
  ["RBA dataset จริง", "Wiefling 2022 — 31,269,264 logins (~9 GB), มี ground-truth (Is Account Takeover / Attack IP)"],
  ["Sampling", "normal 10,000 (reservoir) + ATO จริง 100–141 เคส"],
  ["Synthetic 40 แถว", "สร้างเอง 9 attack scenario เพราะ RBA ไม่มี feature ระบบ (passkey/session) + ATO จริงน้อย/ไม่หลากหลาย"],
  ["2 ชุดข้อมูล", "semi-synthetic (10,140 แถว, 23 feat) + real-only (10,141 แถว, 12 feat จริงล้วน)"],
], [2200, 7160]));
kids.push(p("เครื่องมือ: sample_rba_base.py, build_benchmark.py, build_real_only.py", { size: 16, italics: true }));

kids.push(h2("ขั้นที่ 3 — เตรียมและทำความสะอาดข้อมูล"));
kids.push(bullet("Filtering: normal ต้องสะอาด (ไม่ปน attack-IP / ATO / login fail)"));
kids.push(bullet("Type conversion: True/False (string) → 1.0/0.0"));
kids.push(bullet("Parsing: timestamp → datetime (2 รูปแบบ); user-agent → browser family + device type"));
kids.push(bullet("จัดการ missing/รก: City=\"-\" ตัดทิ้ง, แถว field < 16 ข้าม, timestamp เสียข้าม"));
kids.push(bullet("Memory hygiene (real-only): ua → hash, cap 4,000 login/user (กัน OOM จาก attack account)"));
kids.push(bullet("Cold start: history < 5 session → personalized feature = neutral (0) ไม่ลงโทษ user ใหม่"));

kids.push(h2("ขั้นที่ 4 — เลือกและสร้างฟีเจอร์"));
kids.push(table(["ชุด", "features", "หมายเหตุ"], [
  ["Experiment A", "13", "baseline RBA (temporal/geo/device/velocity/brute/threat/session)"],
  ["Experiment B", "19", "+ Tier-1 (concurrent, active_subsystem, weekday_usage, scope, permission_change_age, confirmed_incident)"],
  ["Experiment C", "23", "+ Passkey (count, age, recently_added, last_used)"],
  ["real-only", "12", "derive จาก RBA จริงล้วน (ตัด active_session_count ที่ RBA ไม่มี)"],
], [1900, 1000, 6460]));
kids.push(bullet("Engineering: is_thailand = home-country proxy, log-scale velocity, history features (online RBA)"));
kids.push(bullet("Scaling: StandardScaler (จำเป็นกับ OCSVM/LOF; IForest invariant) · Feature importance: SHAP (ขั้น 6)"));

kids.push(h2("ขั้นที่ 5 — เลือกอัลกอริทึมและฝึกสอนโมเดล"));
kids.push(table(["โมเดล", "ประเภท", "setting"], [
  ["IsolationForest", "tree-based", "n_estimators=200, contamination=prevalence"],
  ["OneClassSVM", "kernel (RBF)", "gamma=scale, nu≈prevalence"],
  ["LocalOutlierFactor", "density", "n_neighbors=20 (novelty=True ตอน split)"],
], [2600, 2200, 4560]));
kids.push(bullet("2 โปรโตคอลฝึก: (ก) in-sample — fit+score ชุดเดียวกัน (มาตรฐาน unsupervised)"));
kids.push(bullet("(ข) proper (one-class, group-by-user) — fit เฉพาะ normal ของ train users → test held-out + ATO; threshold จาก train; 10 splits (วัด generalization จริง)"));
kids.push(p("Label ไม่ถูกใช้ตอน train — ใช้เฉพาะวัดผล", { bold: true }));

kids.push(h2("ขั้นที่ 6 — ประเมินโมเดล"));
kids.push(table(["การประเมิน", "ผลสรุป"], [
  ["Model comparison (semi-synth, C)", "OCSVM ดีสุด PR-AUC 0.844 / ROC 0.963"],
  ["Ablation A→B→C", "Tier-1 เพิ่ม Recall; Passkey เพิ่ม Precision"],
  ["Robustness (20 seeds + Wilcoxon)", "OCSVM > IForest บน synthetic (p<0.0001)"],
  ["Real-only (proper split)", "IForest ROC 0.890 / PR 0.427; IForest ≈ OCSVM บนข้อมูลจริง"],
  ["Semi-synth vs Real (apples-to-apples)", "synthetic ประเมินเกินจริง PR-AUC ~1.8 เท่า"],
  ["SHAP (อธิบายผล)", "passkey = trust signal (ลด FP); ตัวขับ anomaly = new_device/new_country/failed/concurrent"],
  ["SHAP cost (IForest vs OCSVM)", "Tree 3 ms/row exact vs Kernel 203 ms/row approx (~66×), overlap 4/10"],
], [3400, 5960]));

kids.push(h2("ขั้นที่ 7 — นำไปใช้งานจริง"));
kids.push(table(["ด้าน", "การตัดสินใจ"], [
  ["โมเดลที่เลือก", "IsolationForest — explainable (SHAP exact+เร็ว), เสมอ OCSVM บนข้อมูลจริง, เสถียร, scale เชิงเส้น"],
  ["OneClassSVM", "เก็บเป็น comparative upper-bound / secondary signal (ไม่ใช่ primary เพราะ SHAP ช้า+approx)"],
  ["Integration", "ML service /v1/score (FastAPI) → Hub 4-layer RBA (Rule + Behavior + IForest + Aggregation)"],
  ["Shadow Mode", "ML_SHADOW_MODE=true — score แต่ยังไม่ block (decision = would_mfa/would_block)"],
  ["Retrain", "generate_data → train_model → restart hub-backend เมื่อ feature เปลี่ยน"],
  ["งานต่อไป", "validation บน traffic จริงของระบบ + เก็บ attack จริง (red-team)"],
], [2200, 7160]));
kids.push(new Paragraph({ children: [new PageBreak()] }));

// 1. Objectives
kids.push(h1("1. วัตถุประสงค์"));
kids.push(p("การทดลองนี้พิสูจน์ 4 ประเด็นตาม docs/การทดสอบ.md:"));
["การเพิ่ม Feature Engineering ช่วยเพิ่มการตรวจจับ Account Takeover (ATO) ได้หรือไม่",
 "การเพิ่ม Passkey Trust Layer ช่วยลด False Positive ได้หรือไม่",
 "โมเดลใดเหมาะสมที่สุดสำหรับ Hybrid Risk-Based Authentication",
 "นำผลไปใช้จริงใน Identity Hub ได้หรือไม่"].forEach(t => kids.push(bullet(t)));

// 2. Dataset
kids.push(h1("2. Dataset"));
kids.push(p("อ้างอิงฐานข้อมูลจริง RBA dataset (Wiefling 2022) ขนาด ~9 GB / 31,269,264 logins สตรีม-sample ด้วย reservoir sampling แล้วยกระดับเป็น schema login_sessions พร้อม engineered features 23 ตัว และเติม synthetic attack ที่เนียน 40 แถว"));
kids.push(table(["ส่วนประกอบ", "จำนวน", "ที่มา"], [
  ["normal (label 0)", "10,000", "sample จริงจาก RBA (clean: ไม่ ATO/ไม่ attack-IP/login สำเร็จ)"],
  ["anomaly จริง (label 1)", "100", "Is Account Takeover=True (ทั้งชุดมีเพียง 141)"],
  ["synthetic stealth (label 1)", "40", "สังเคราะห์ — เนียน/หลากหลาย 9 scenario"],
  [{ v: "รวม", bold: true }, { v: "10,140", bold: true }, { v: "attack 1.38% (imbalanced สมจริง)", bold: true }],
], [2600, 1400, 5360]));
kids.push(p("คอลัมน์: 19 raw (schema login_sessions) + 22 engineered feature + label/scenario/source = 44 คอลัมน์", { size: 18, italics: true }));

kids.push(h2("2.1 Attack scenarios (40 synthetic)"));
kids.push(table(["Scenario", "n", "สัญญาณที่ซ่อน"], [
  ["credential_stuffing_stealth", "5", "failed_logins 4–8 (ไม่สุดโต่ง) + login_count สูงนิด"],
  ["new_device_stealth", "5", "is_new_device=1 แต่ browser family เดิม + เพิ่ม passkey เอง"],
  ["new_country_stealth", "5", "ประเทศใหม่แบบ plausible (เพื่อนบ้าน)"],
  ["attack_ip_stealth", "5", "is_attack_ip=1 แต่ทุกอย่างดูปกติ (VPN exit)"],
  ["passkey_abuse", "5", "new_passkey_recently_added=1 + เครื่องใหม่"],
  ["lateral_movement", "4", "active_subsystem_count 3–5 + concurrent"],
  ["concurrent_sessions", "4", "concurrent_session_count 4–10"],
  ["privilege_abuse", "4", "permission_change_age 0–2 วัน + scope สูง"],
  ["blended_low_and_slow", "3", "หลายสัญญาณอ่อนพร้อมกัน — จับยากสุด"],
], [3200, 700, 5460]));
kids.push(p("label ใช้ \"วัดผล\" เท่านั้น — โมเดล unsupervised เทรนจาก features อย่างเดียว ไม่เห็น label; label ใช้คำนวณ metrics", { bold: true }));

// 3. Experiment design
kids.push(h1("3. การออกแบบการทดลอง (A / B / C)"));
kids.push(table(["Experiment", "Features", "เพิ่มอะไร"], [
  ["A — Baseline RBA", "13", "Temporal/Geo/Device/Velocity/Brute/Threat/Session"],
  ["B — Enhanced", "19", "+ Tier-1: concurrent, active_subsystem, weekday_usage, scope, permission_change_age, confirmed_incident"],
  ["C — + Passkey Trust", "23", "+ passkey_count, passkey_age, new_passkey_recently_added, passkey_last_used"],
], [2600, 1200, 5560]));

// 4. Model comparison
kids.push(h1("4. ผลเปรียบเทียบโมเดล"));
kids.push(p("เทรน IsolationForest / OneClassSVM / LocalOutlierFactor (StandardScaler, contamination=1.38%) วัด Precision/Recall/F1/ROC-AUC/PR-AUC (PR-AUC = ตัวหลัก เพราะ imbalanced)"));
const mc = (P, R, F, RO, PR, win) => [P, R, F, RO, win ? { v: PR, fill: HL, bold: true } : PR];
kids.push(table(["Exp / Model", "Prec", "Recall", "F1", "ROC-AUC", "PR-AUC"], [
  ["A / IsolationForest", ...mc("0.700", "0.700", "0.700", "0.928", "0.726")],
  ["A / OneClassSVM", ...mc("0.551", "0.693", "0.614", "0.923", "0.723")],
  ["A / LOF", ...mc("0.414", "0.414", "0.414", "0.692", "0.389")],
  ["B / IsolationForest", ...mc("0.714", "0.714", "0.714", "0.930", "0.749")],
  ["B / OneClassSVM", ...mc("0.512", "0.757", "0.611", "0.924", "0.782", true)],
  ["B / LOF", ...mc("0.400", "0.400", "0.400", "0.696", "0.410")],
  ["C / IsolationForest", ...mc("0.707", "0.707", "0.707", "0.928", "0.734")],
  [{ v: "C / OneClassSVM", bold: true }, "0.609", "0.836", "0.705", "0.963", { v: "0.844", fill: HL, bold: true }],
  ["C / LOF", ...mc("0.500", "0.500", "0.500", "0.751", "0.536")],
], [3060, 1100, 1100, 1100, 1500, 1500]));
kids.push(cap("ตาราง 4.1 — ผลทุก Experiment × โมเดล (ไฮไลต์ = PR-AUC ดีสุดต่อชุด)"));
kids.push(image("C/metrics_comparison.png", 600));
kids.push(cap("รูป 4.1 — Metrics comparison (Experiment C)"));
kids.push(image("C/confusion_matrices.png", 640));
kids.push(cap("รูป 4.2 — Confusion matrices (Experiment C) — OCSVM จับ attack 117/140, IForest สมดุล FP/FN"));
kids.push(sideBySide("C/roc_curves.png", "C/pr_curves.png", 330));
kids.push(cap("รูป 4.3 — ROC (ซ้าย) และ Precision-Recall (ขวา), Experiment C"));

// 5. Ablation
kids.push(h1("5. Ablation — ผลของการเพิ่ม Feature (A → B → C)"));
kids.push(image("ablation_pr_auc.png", 640));
kids.push(cap("รูป 5.1 — PR-AUC และ F1 เมื่อเพิ่ม feature ทีละชุด"));
kids.push(bullet("A → B (เพิ่ม Tier-1): OCSVM PR-AUC 0.723 → 0.782, Recall 0.693 → 0.757 — ยืนยันว่า Tier-1 ช่วยเพิ่มการตรวจจับ"));
kids.push(bullet("B → C (เพิ่ม Passkey): OCSVM Precision 0.512 → 0.609, F1 0.611 → 0.705 — Passkey Trust Layer ลด False Positive"));

// 6. SHAP
kids.push(h1("6. Explainable AI (SHAP)"));
kids.push(p("SHAP TreeExplainer บน IsolationForest — global importance = mean(|SHAP|); ทิศทางบน attack rows: ค่าลบ = ดันเข้าหา anomaly, ค่าบวก = ดึงเข้าหาปกติ (trust)"));
kids.push(table(["#", "Feature (Exp C)", "mean|SHAP|", "ทิศบน attack"], [
  ["1", "permission_change_age [Tier-1]", "0.345", "→ anomaly"],
  ["2", "active_subsystem_count [Tier-1]", "0.341", "→ anomaly"],
  ["3", "active_session_count", "0.331", "→ anomaly"],
  ["4", "is_thailand", "0.265", "→ anomaly"],
  ["5", "concurrent_session_count [Tier-1]", "0.255", "→ anomaly"],
  ["6", "is_new_device", "0.245", "→ anomaly"],
  [{ v: "7", fill: HL }, { v: "passkey_age_days [Passkey]", fill: HL, bold: true }, { v: "0.230", fill: HL }, { v: "→ normal (trust)", fill: HL, bold: true }],
  ["9", "country_change_count_30d", "0.196", "→ anomaly"],
  ["10", "failed_logins_24h", "0.179", "→ anomaly"],
  [{ v: "12", fill: HL }, { v: "passkey_count [Passkey]", fill: HL, bold: true }, { v: "0.162", fill: HL }, { v: "→ normal (trust)", fill: HL, bold: true }],
], [600, 4360, 1800, 2600]));
kids.push(cap("ตาราง 6.1 — Top features (Experiment C) — แถวไฮไลต์ = Passkey ทำหน้าที่ trust signal"));
kids.push(sideBySide("C/shap_feature_importance.png", "C/shap_summary_beeswarm.png", 330));
kids.push(cap("รูป 6.1 — SHAP importance (ซ้าย) และ beeswarm summary (ขวา), Experiment C"));
kids.push(p("Insight: passkey_age_days และ passkey_count เป็นกลุ่มเดียวที่ SHAP เป็นบวกบน attack rows = ดึงเข้าหา \"ปกติ\" → กลไกที่ทำให้ Passkey Trust Layer ลด False Positive ตรงตามดีไซน์ (สอดคล้องผล B→C)", { bold: true }));

// 7. Robustness
kids.push(h1("7. Robustness Study"));
kids.push(p("20 seeds × subsample 80% (stratified), Experiment C — รายงาน mean ± std [95% CI] ของ PR-AUC/ROC-AUC (threshold-free)"));
kids.push(table(["Model", "PR-AUC (mean±std [95% CI])", "ROC-AUC"], [
  [{ v: "OneClassSVM", bold: true }, { v: "0.809 ± 0.017 [0.782, 0.844]", fill: HL, bold: true }, "0.965 [0.954, 0.970]"],
  ["IsolationForest", "0.747 ± 0.018 [0.709, 0.780]", "0.925 [0.908, 0.936]"],
  ["LocalOutlierFactor", "0.575 ± 0.018 [0.551, 0.606]", "0.779 [0.762, 0.801]"],
], [2600, 4360, 2400]));
kids.push(p("Wilcoxon signed-rank (PR-AUC, OCSVM vs IForest): mean diff +0.063, W=0, p<0.0001 → OCSVM ชนะครบทั้ง 20/20 seeds — ความต่าง มีนัยสำคัญทางสถิติ ไม่ใช่ noise"));
kids.push(h2("7.1 Operating-point sweep (Experiment C)"));
kids.push(table(["flag-rate", "IForest P / R / F1", "OCSVM P / R / F1"], [
  ["0.50%", "1.000 / 0.364 / 0.534", "1.000 / 0.364 / 0.534"],
  ["1.00%", "0.951 / 0.693 / 0.802", "0.971 / 0.707 / 0.818"],
  ["1.38%", "0.707 / 0.707 / 0.707", "0.750 / 0.750 / 0.750"],
  ["2.00%", "0.493 / 0.714 / 0.583", "0.581 / 0.843 / 0.688"],
  ["5.00%", "0.207 / 0.750 / 0.325", "0.250 / 0.907 / 0.393"],
], [1800, 3780, 3780]));
kids.push(p("ที่จุดทำงานจริง (flag ≤1%) สองโมเดลเกือบเท่ากัน — OCSVM ทิ้งห่างตอน flag เยอะ (recall สูงกว่า)", { italics: true }));

// 8. Decision
kids.push(h1("8. การตัดสินใจเลือกโมเดล (ตามบริบทจริง)"));
kids.push(p("ไม่เปลี่ยน production scorer เป็น OCSVM แบบรื้อทั้งหมด — แต่ยอมรับว่า OCSVM detection เหนือกว่าจริง และใช้กลยุทธ์ hybrid", { bold: true }));
kids.push(table(["ปัจจัย", "ได้เปรียบ", "หมายเหตุ"], [
  ["Detection (PR-AUC/ROC-AUC)", "OneClassSVM", "+0.063, significant (p<0.0001)"],
  ["Detection @ จุดทำงาน ≤1%", "เกือบเท่ากัน", "regime ที่ deploy จริง"],
  ["Explainability (SHAP รายเคส)", "IsolationForest", "TreeExplainer exact+เร็ว (auth ต้อง audit ได้)"],
  ["Latency / scalability", "IsolationForest", "เชิงเส้น; OCSVM O(n²–n³)"],
  ["เสถียรต่อ drift/hyperparameter", "IsolationForest", "OCSVM ไวต่อ nu/gamma"],
  ["External validity", "เสมอ", "benchmark กึ่ง-synthetic — significance ≠ generalize"],
], [3000, 2200, 4160]));
kids.push(p("ข้อสรุป: เลือก IsolationForest เป็น primary online scorer (explainable + เร็ว + สเกลได้) และใช้ OneClassSVM เป็น secondary/shadow signal เพื่อดึง recall ที่เก่งกว่ามาเสริม", { bold: true }));

// 9. Real-only benchmark
kids.push(new Paragraph({ children: [new PageBreak()] }));
kids.push(h1("9. ผลบนข้อมูลจริง 100% (Real-Only Benchmark)"));
kids.push(p("เพื่อความซื่อสัตย์ ทำชุด real-only ที่ feature ทุกตัว derive จาก RBA จริง (ไม่มี synthetic): sample login history จริงต่อ user แล้วคำนวณ feature จากประวัติก่อนหน้า (online RBA) + ใช้ ATO จริงทั้งหมด 141 เคส"));
kids.push(table(["รายการ", "ค่า"], [
  ["total rows", "10,141"],
  ["normal (label 0)", "10,000 — จาก 97,466 login จริง (history จริงต่อ user)"],
  ["attack (label 1)", "141 — ATO จริงทั้งหมดในชุด RBA"],
  ["features", "12 (Experiment A 13 ตัว − active_session_count ที่ RBA ไม่มี logout)"],
], [2400, 6960]));
kids.push(p("failed_logins_24h = Login Successful=False จริง · home country = NO (Norway, modal)", { size: 18, italics: true }));
kids.push(h2("9.1 ผล in-sample (flag @ 1.39%)"));
kids.push(table(["Model", "Prec", "Recall", "F1", "ROC-AUC", "PR-AUC"], [
  ["IsolationForest", "0.057", "0.057", "0.057", "0.872", "0.079"],
  ["OneClassSVM", "0.156", "0.156", "0.156", "0.764", "0.093"],
  ["LocalOutlierFactor", "0.071", "0.071", "0.071", "0.451", "0.021"],
], [3060, 1100, 1100, 1100, 1500, 1500]));
kids.push(image("REAL/confusion_matrices.png", 640));
kids.push(cap("รูป 9.1 — Confusion matrices REAL-ONLY: IForest จับ ATO ได้ 8/141, OCSVM 22/141 (in-sample)"));
kids.push(sideBySide("REAL/roc_curves.png", "REAL/pr_curves.png", 330));
kids.push(cap("รูป 9.2 — ROC (ซ้าย) และ Precision-Recall (ขวา), REAL-ONLY"));

kids.push(h2("9.2 เทียบ Semi-Synthetic vs Real-Only (จุดสำคัญ)"));
kids.push(table(["Metric", "semi-synth (attack สังเคราะห์)", "real (ATO จริง)", "ต่าง"], [
  ["IForest ROC-AUC", "0.928", "0.872", "ใกล้เคียง"],
  [{ v: "IForest PR-AUC", bold: true }, "0.726", { v: "0.079", fill: HL, bold: true }, "~9× ต่ำลง"],
  [{ v: "OCSVM PR-AUC", bold: true }, "0.723", { v: "0.093", fill: HL, bold: true }, "~8× ต่ำลง"],
  ["TP @ flag 1.39% (IForest)", "~99/140", "8/141", "ตกฮวบ"],
], [2700, 2800, 2160, 1700]));
kids.push(bullet("Semi-synthetic ประเมินสูงเกินจริง — attack สังเคราะห์แยกง่ายเกินไป (PR-AUC ~9 เท่า)"));
kids.push(bullet("ROC-AUC ยังพอใช้ (0.87) แต่ PR-AUC พังที่ 0.079 → PR-AUC คือ metric ที่ซื่อสัตย์ (ยืนยัน §11)"));
kids.push(bullet("ATO จริงตรวจยากด้วย 12 behavioral feature ลำพัง (สอดคล้อง Wiefling 2022) → เป็นแรงจูงใจของ 4-layer RBA + passkey/session layer"));
kids.push(sideBySide("REAL/shap_feature_importance.png", "REAL/shap_summary_beeswarm.png", 330));
kids.push(cap("รูป 9.3 — SHAP importance (ซ้าย) และ beeswarm (ขวา), REAL-ONLY"));

// 10. Proper train/test
kids.push(h1("10. Proper Train/Test Protocol (One-Class, Group-by-User)"));
kids.push(p("โปรโตคอลที่ถูกต้องสำหรับวัด generalization (ไม่ใช่ in-sample): เทรน normal-only ของ train users (70%) → ทดสอบบน normal ของ test users + ATO จริงทั้งหมด; threshold ตั้งจาก train; group-by-user กัน leakage; ทำซ้ำ 10 splits"));
kids.push(table(["Model", "ROC-AUC", "PR-AUC", "F1@1%", "Prec", "Recall"], [
  [{ v: "IsolationForest", bold: true }, { v: "0.890 ± 0.041", fill: HL, bold: true }, { v: "0.427 ± 0.166", fill: HL, bold: true }, "0.325", "0.740", "0.265"],
  ["OneClassSVM", "0.839 ± 0.028", "0.414 ± 0.164", "0.486", "0.541", "0.500"],
  ["LocalOutlierFactor", "0.489 ± 0.085", "0.103 ± 0.067", "0.074", "0.226", "0.050"],
], [2700, 1900, 1900, 1100, 900, 860]));
kids.push(cap("ตาราง 10.1 — Generalization (mean ± std, 10 splits) — ตัวเลขหลักของ \"ผลบนข้อมูลจริง\""));
kids.push(h2("10.1 ข้อค้นพบสำคัญ"));
kids.push(bullet("in-sample ให้ผลแย่เกินจริงสำหรับ one-class — fit บนข้อมูลปน attack 1.4% ทำให้แบบจำลอง normal เพี้ยน (PR-AUC 0.079); โปรโตคอลถูกต้อง (เทรน normal-only สะอาด) ได้ 0.427 → in-sample ไม่ได้ optimistic เสมอ"));
kids.push(bullet("ROC-AUC เทียบได้ (prevalence-invariant): 0.872 → 0.890 ใกล้เคียง — ยืนยันสัญญาณ ranking เสถียร (PR-AUC สูงขึ้นส่วนหนึ่งเพราะ test prevalence ~4.5%; อย่าเทียบ PR-AUC ข้าม prevalence)"));
kids.push(bullet("บนข้อมูลจริง + โปรโตคอลถูกต้อง: IForest ≈ OCSVM (0.427 vs 0.414, std ทับกัน) — ต่างจาก semi-synthetic ที่ OCSVM ชนะขาด → สนับสนุนการเลือก IsolationForest"));
kids.push(bullet("variance สูง (±0.166) เพราะ ATO จริงมีแค่ 141 เคส → ข้อมูล attack จริงไม่พอสำหรับข้อสรุปเด็ดขาด"));
kids.push(p("สำหรับเล่ม: ใช้ proper protocol นี้เป็นตัวเลขหลักของ \"ผลบนข้อมูลจริง\" (ไม่ใช่ in-sample) และรายงาน ROC-AUC คู่ PR-AUC พร้อม std เสมอ", { bold: true }));

// 10.5 Simulated dataset (anchor real users)
kids.push(new Paragraph({ children: [new PageBreak()] }));
kids.push(h1("10.5 ชุดที่ 3 — Simulated (Anchor ผู้ใช้จริงของระบบ)"));
kids.push(p("ดึง \"ผู้ใช้จริง + สิทธิ์จริง\" จากฐานข้อมูลระบบ (ผู้ใช้ที่เคย login จริง 5 คน) เป็นต้นแบบ แล้ว clone เป็น persona รวม 150 คน จำลองพฤติกรรม login 1 เดือน เข้าได้เฉพาะ subsystem ที่มีสิทธิ์จริง + ฉีด anomaly แบบคุมระดับ (1/2/3) — เป็นชุดที่ anchor กับ identity graph ของระบบเราเอง (ไม่ใช่ข้อมูลต่างประเทศ)"));
kids.push(table(["รายการ", "ค่า"], [
  ["total rows", "9,673"],
  ["attack (label 1)", "300 (3.1%)"],
  ["users", "จริง 5 + clone persona 145"],
  ["features", "23 (Experiment C) — history-based คำนวณจาก login จริงต่อ user; scope อิง subsystem จริง"],
  ["ระดับ anomaly", "🟡 level1=35 · 🟠 level2=47 · 🔴 level3=253 + คอลัมน์ columns_changed"],
], [2400, 6960]));
kids.push(h2("10.5.1 ผล in-sample (flag @ 3.1%)"));
kids.push(table(["Model", "Prec", "Recall", "F1", "ROC-AUC", "PR-AUC"], [
  [{ v: "IsolationForest", bold: true }, "0.830", "0.830", "0.830", "0.984", { v: "0.881", fill: HL, bold: true }],
  ["OneClassSVM", "0.494", "0.510", "0.502", "0.958", "0.486"],
  ["LocalOutlierFactor", "0.073", "0.073", "0.073", "0.431", "0.032"],
], [3060, 1100, 1100, 1100, 1500, 1500]));
kids.push(h2("10.5.2 การจับ attack ตามระดับความเนียน (IForest) — จุดเด่น"));
kids.push(table(["ระดับ", "ลักษณะ", "จับได้"], [
  ["🟡 1 (IP เปลี่ยนเดี่ยว, label=0)", "ปกติที่ดูแปลก", "0/35 → false positive ต่ำ"],
  [{ v: "🟠 2 (country/device เดี่ยว)", bold: true }, "เนียน", { v: "1/47 → จับยากมาก", fill: HL, bold: true }],
  ["🔴 3 (ATO เต็มรูป)", "ชัดเจน", "248/253 → จับเกือบหมด"],
], [3400, 2200, 3760]));
kids.push(p("→ พิสูจน์ว่าโมเดลจับ ATO ชัดได้ แต่ attack เนียนที่เปลี่ยนคอลัมน์เดียวยังจับแทบไม่ได้ (ความท้าทายจริงของ RBA)", { bold: true }));
kids.push(image("SIM/confusion_matrices.png", 640));
kids.push(cap("รูป 10.5a — Confusion matrices (SIMULATED, anchor ผู้ใช้จริง)"));
kids.push(sideBySide("SIM/roc_curves.png", "SIM/pr_curves.png", 330));
kids.push(cap("รูป 10.5b — ROC และ Precision-Recall (SIMULATED)"));
kids.push(h2("10.5.3 ผล proper split (one-class, group-by-user, 10 splits)"));
kids.push(table(["Model", "ROC-AUC", "PR-AUC", "Recall@1%"], [
  [{ v: "OneClassSVM", bold: true }, "0.984 ± 0.000", { v: "0.703 ± 0.011", fill: HL, bold: true }, "1.000"],
  ["IsolationForest", "0.880 ± 0.013", "0.328 ± 0.037", "0.311"],
  ["LocalOutlierFactor", "0.952 ± 0.002", "0.299 ± 0.016", "0.999"],
], [2800, 2400, 2400, 1760]));
kids.push(p("ต่างจาก real-only (IForest≈OCSVM) — บนชุดนี้ OCSVM/LOF เด่นกว่า เพราะ attack ที่ฉีดเป็น signal-rich (is_attack_ip=1, ต่างประเทศ) → เทรน one-class บน normal สะอาดแล้ว attack อยู่นอกขอบเขตชัด; level-2 เนียนยังยากทุกโมเดล", { italics: true }));
kids.push(sideBySide("SIM/shap_feature_importance.png", "SIM/shap_summary_beeswarm.png", 330));
kids.push(cap("รูป 10.5c — SHAP importance และ beeswarm (SIMULATED, IForest)"));

// 11. Methodology detail + 40 synthetic rows
kids.push(new Paragraph({ children: [new PageBreak()] }));
kids.push(h1("11. ระเบียบวิธีโดยละเอียด + ข้อมูล Synthetic ทั้ง 40 แถว"));
kids.push(h2("11.1 การเลือกข้อมูล (Data Selection)"));
kids.push(bullet("เลือก RBA dataset (Wiefling 2022) — login จริงที่ใหญ่สุดในงาน RBA (31.3M) + มี ground-truth (Is Account Takeover/Attack IP) → อ้างอิงวิชาการได้"));
kids.push(bullet("ไม่ใช้ \"synthetic ล้วน 500k\" (แผนเดิม) — ไม่มีฐานความจริง ตัวเลขสะท้อนแค่กฎที่เรา gen เอง"));
kids.push(bullet("ทำ 2 ชุด: semi-synthetic (ทดสอบ pipeline + ablation 23 feature) และ real-only (ATO จริง — กันการอ้างเกินจริง)"));
kids.push(h2("11.2 ทำไมต้องสร้างข้อมูลเอง (Synthetic)"));
kids.push(bullet("RBA ไม่มีคอลัมน์ passkey/session/subsystem/scope/permission → 11 feature นี้ต้องสังเคราะห์"));
kids.push(bullet("ATO จริงมีแค่ 141 เคส และไม่หลากหลาย → สร้าง 40 attack stealth ครอบคลุม 9 pattern"));
kids.push(bullet("ต้องการ attack ที่ \"เนียน\" (raw ดูปกติ ฝัง anomaly แบบ multi-signal) เพื่อทดสอบขีดจำกัดโมเดล"));

kids.push(h2("11.3 ข้อมูล Synthetic ทั้ง 40 แถว"));
kids.push(p("ตัวย่อ: hr=hour, ctry=country, newC=is_new_country, newD=is_new_device, fail=failed_logins_24h, conc=concurrent_session_count, asub=active_subsystem_count, npk=new_passkey_recently_added, perm=permission_change_age(วัน), aip=is_attack_ip · เต็มทุกคอลัมน์ใน synthetic_attacks_40.csv", { size: 16, italics: true }));
const SYN = [
  ["1", "cred_stuffing", "13", "TH", "0", "0", "5", "0", "1", "0", "180", "0"],
  ["2", "cred_stuffing", "15", "TH", "0", "0", "6", "0", "1", "0", "9999", "0"],
  ["3", "cred_stuffing", "14", "TH", "0", "0", "4", "0", "1", "0", "90", "0"],
  ["4", "cred_stuffing", "11", "TH", "0", "0", "5", "0", "1", "0", "9999", "0"],
  ["5", "cred_stuffing", "14", "TH", "0", "0", "6", "0", "1", "0", "9999", "0"],
  ["6", "new_device", "16", "TH", "0", "1", "0", "0", "1", "1", "180", "0"],
  ["7", "new_device", "9", "TH", "0", "1", "0", "0", "1", "1", "90", "0"],
  ["8", "new_device", "10", "TH", "0", "1", "0", "0", "1", "1", "90", "0"],
  ["9", "new_device", "9", "TH", "0", "1", "0", "0", "1", "1", "365", "0"],
  ["10", "new_device", "13", "TH", "0", "1", "0", "0", "1", "1", "180", "0"],
  ["11", "new_country", "16", "LA", "1", "0", "0", "0", "1", "0", "365", "0"],
  ["12", "new_country", "15", "LA", "1", "0", "0", "0", "1", "0", "90", "0"],
  ["13", "new_country", "16", "LA", "1", "0", "0", "0", "1", "0", "90", "0"],
  ["14", "new_country", "15", "SG", "1", "0", "0", "0", "1", "0", "365", "0"],
  ["15", "new_country", "14", "JP", "1", "0", "0", "0", "1", "0", "9999", "0"],
  ["16", "attack_ip", "9", "TH", "0", "0", "0", "0", "1", "0", "9999", "1"],
  ["17", "attack_ip", "13", "TH", "0", "0", "0", "0", "1", "0", "180", "1"],
  ["18", "attack_ip", "10", "TH", "0", "0", "0", "0", "1", "0", "90", "1"],
  ["19", "attack_ip", "11", "TH", "0", "0", "0", "0", "1", "0", "9999", "1"],
  ["20", "attack_ip", "9", "TH", "0", "0", "0", "0", "1", "0", "180", "1"],
  ["21", "passkey_abuse", "11", "TH", "0", "1", "0", "0", "1", "1", "9999", "0"],
  ["22", "passkey_abuse", "16", "TH", "0", "1", "0", "0", "1", "1", "365", "0"],
  ["23", "passkey_abuse", "15", "TH", "0", "1", "0", "0", "1", "1", "180", "0"],
  ["24", "passkey_abuse", "10", "TH", "0", "1", "0", "0", "1", "1", "9999", "0"],
  ["25", "passkey_abuse", "9", "TH", "0", "1", "0", "0", "1", "1", "365", "0"],
  ["26", "lateral_move", "15", "TH", "0", "0", "0", "2", "4", "0", "180", "0"],
  ["27", "lateral_move", "10", "TH", "0", "0", "0", "2", "4", "0", "180", "0"],
  ["28", "lateral_move", "15", "TH", "0", "0", "0", "2", "5", "0", "180", "0"],
  ["29", "lateral_move", "13", "TH", "0", "0", "0", "2", "3", "0", "9999", "0"],
  ["30", "concurrent", "9", "TH", "0", "0", "0", "8", "1", "0", "180", "0"],
  ["31", "concurrent", "10", "TH", "0", "0", "0", "8", "1", "0", "9999", "0"],
  ["32", "concurrent", "13", "TH", "0", "0", "0", "8", "1", "0", "9999", "0"],
  ["33", "concurrent", "11", "TH", "0", "0", "0", "8", "1", "0", "9999", "0"],
  ["34", "privilege", "9", "TH", "0", "0", "0", "0", "1", "0", "0", "0"],
  ["35", "privilege", "10", "TH", "0", "0", "0", "0", "1", "0", "2", "0"],
  ["36", "privilege", "14", "TH", "0", "0", "0", "0", "1", "0", "1", "0"],
  ["37", "privilege", "16", "TH", "0", "0", "0", "0", "1", "0", "1", "0"],
  ["38", "blended", "14", "TH", "0", "1", "0", "1", "1", "1", "180", "0"],
  ["39", "blended", "16", "TH", "0", "1", "0", "1", "1", "0", "365", "0"],
  ["40", "blended", "15", "TH", "0", "1", "0", "1", "1", "0", "90", "0"],
];
kids.push(table(["#", "scenario", "hr", "ctry", "newC", "newD", "fail", "conc", "asub", "npk", "perm", "aip"],
  SYN, [360, 1900, 710, 710, 710, 710, 710, 710, 710, 710, 710, 710]));
kids.push(cap("ตาราง 11.1 — ข้อมูล synthetic ครบ 40 แถว (9 scenario)"));

kids.push(h2("11.4 กระบวนการ (Pipeline)"));
kids.push(p("1) Sampling — reservoir (รอบ 1) / 2-pass per-user history (รอบ 2); 2) Cleaning — filter normal สะอาด, True/False→1/0, parse timestamp+UA, ตัด field รก, cap login/user; 3) Transformation — derive 23/12 features, is_thailand=home proxy, log-scale, StandardScaler; 4) Training — IForest/OCSVM/LOF, in-sample + proper one-class group-by-user; 5) Evaluation — P/R/F1/ROC-AUC/PR-AUC + SHAP (label ใช้วัดผลเท่านั้น)"));

// 12. SHAP on OCSVM
kids.push(h1("12. SHAP บน OneClassSVM — เหตุผลที่เลือก IsolationForest"));
kids.push(p("เปรียบเทียบต้นทุนและความสอดคล้องของการอธิบาย (explainability) ระหว่างสองโมเดล"));
kids.push(table(["Explainer", "ขอบเขต", "เวลา", "ต่อแถว", "ชนิด"], [
  ["TreeExplainer (IForest)", "ทั้งชุด 10,140 แถว", "31 s", "3.07 ms", "exact"],
  [{ v: "KernelExplainer (OCSVM)", bold: true }, "แค่ 300 แถว (bg=30)", "61 s", { v: "203 ms", fill: HL, bold: true }, "approximate"],
], [2900, 2400, 1200, 1560, 1300]));
kids.push(bullet("OCSVM อธิบายช้ากว่า ~66 เท่า และเป็นค่าประมาณ → explain ทุก login แบบ real-time ใน audit UI ไม่ได้"));
kids.push(bullet("Top-10 feature importance overlap (IForest ∩ OCSVM) = แค่ 4/10 → OCSVM ให้คำอธิบายต่างและไม่นิ่ง"));
kids.push(image("shap_ocsvm_vs_iforest.png", 640));
kids.push(cap("รูป 12.1 — SHAP importance: IForest (TreeExplainer, exact) vs OCSVM (KernelExplainer, approx)"));
kids.push(p("สรุป: เลือก IsolationForest ไป production เพราะ explainable (SHAP exact+เร็ว) + เสมอ OCSVM บนข้อมูลจริง (บท 10) + เสถียร + สเกลได้; OneClassSVM = comparative upper-bound ที่พิสูจน์คุณค่า feature engineering", { bold: true }));

// 13. Limitations
kids.push(h1("13. ข้อจำกัด และงานต่อไป"));
kids.push(bullet("feature passkey/session/scope/permission/incident สังเคราะห์ (RBA ไม่มี) — เหมาะเปรียบเทียบโครงสร้างโมเดล + ablation ไม่ใช่ตัวแทน production"));
kids.push(bullet("is_thailand เป็น proxy ของ home country เพราะ RBA เป็นชุดนอร์เวย์"));
kids.push(bullet("ทำ proper train/test split (one-class, group-by-user) แล้วในบท 10 — งานต่อไป: validation บน traffic จริงของระบบ + เพิ่มข้อมูล attack จริง (red-team) เพราะ ATO จริง 141 เคสยังน้อย"));

// 12. Methodology (full)
kids.push(new Paragraph({ children: [new PageBreak()] }));
kids.push(h1("12. ระเบียบวิธีการทดลอง (Methodology) — รายละเอียดเต็ม"));
kids.push(p("(หมายเหตุ: สำหรับเล่มจริง บทนี้ควรย้ายไปไว้ก่อนบทผล — วางไว้ท้ายเพื่อความสะดวกในการรวมไฟล์)", { italics: true, size: 18, color: "888888" }));

kids.push(h2("12.1 การเลือกข้อมูล (Data Selection)"));
kids.push(bullet("เลือก RBA dataset (Wiefling 2022) — login จริง 31.3M, มี ground-truth (Is Account Takeover/Attack IP), คอลัมน์ตรงกับระบบ, อ้างอิงวิชาการได้"));
kids.push(bullet("ไม่ใช้ synthetic ล้วน 500k (แผนเดิม) — ไม่มีฐานความจริง สะท้อนแค่กฎที่ gen เอง อ่อนเชิงวิชาการ"));
kids.push(bullet("ทำ 2 ชุด: semi-synthetic (ทดสอบ pipeline + ablation 23 feat) และ real-only (วัดผลบนข้อมูลจริงล้วน กันอ้างเกินจริง)"));

kids.push(h2("12.2 ข้อมูลที่สร้างเอง (Synthetic) และเหตุผล"));
kids.push(bullet("RBA ไม่มีคอลัมน์ passkey/session/scope/permission → 11 feature นี้ต้องสังเคราะห์"));
kids.push(bullet("ATO จริงมีแค่ 141 เคส ไม่หลากหลาย → สร้าง 40 stealth attack (9 scenario) ที่ raw ดูปกติแต่ซ่อน anomaly"));
kids.push(table(["scenario", "n", "สัญญาณหลัก"], [
  ["credential_stuffing_stealth (CS)", "5", "fail 4–6 + lc24 6–10 (ไม่สุดโต่ง)"],
  ["new_device_stealth (ND)", "5", "newD=1 + เพิ่ม passkey เอง (npk=1)"],
  ["new_country_stealth (NC)", "5", "newC=1 ประเทศเพื่อนบ้าน (LA/SG/JP)"],
  ["attack_ip_stealth (AIP)", "5", "aip=1 แต่ทุกอย่างดูปกติ"],
  ["passkey_abuse (PK)", "5", "npk=1 + newD=1 (ATO classic)"],
  ["lateral_movement (LM)", "4", "asub 3–5 + conc 2"],
  ["concurrent_sessions (CC)", "4", "conc 8"],
  ["privilege_abuse (PA)", "4", "perm 0–2 วัน + scope 0.87+"],
  ["blended_low_and_slow (BL)", "3", "หลายสัญญาณอ่อนพร้อมกัน"],
], [3600, 700, 5060]));

kids.push(h2("12.2.1 ตารางข้อมูล synthetic ครบทั้ง 40 แถว"));
kids.push(p("ตัวย่อ: hr=hour · newC=is_new_country · newD=is_new_device · fail=failed_logins_24h · conc=concurrent_session · asub=active_subsystem · npk=new_passkey_recently · perm=permission_change_age(วัน) · aip=is_attack_ip · (คอลัมน์เต็มใน synthetic_attacks_40.csv)", { size: 17, italics: true }));
const SROWS = [
  ["1","CS","13","TH","0","0","5","0","1","0","180","0"],["2","CS","15","TH","0","0","6","0","1","0","9999","0"],
  ["3","CS","14","TH","0","0","4","0","1","0","90","0"],["4","CS","11","TH","0","0","5","0","1","0","9999","0"],
  ["5","CS","14","TH","0","0","6","0","1","0","9999","0"],["6","ND","16","TH","0","1","0","0","1","1","180","0"],
  ["7","ND","9","TH","0","1","0","0","1","1","90","0"],["8","ND","10","TH","0","1","0","0","1","1","90","0"],
  ["9","ND","9","TH","0","1","0","0","1","1","365","0"],["10","ND","13","TH","0","1","0","0","1","1","180","0"],
  ["11","NC","16","LA","1","0","0","0","1","0","365","0"],["12","NC","15","LA","1","0","0","0","1","0","90","0"],
  ["13","NC","16","LA","1","0","0","0","1","0","90","0"],["14","NC","15","SG","1","0","0","0","1","0","365","0"],
  ["15","NC","14","JP","1","0","0","0","1","0","9999","0"],["16","AIP","9","TH","0","0","0","0","1","0","9999","1"],
  ["17","AIP","13","TH","0","0","0","0","1","0","180","1"],["18","AIP","10","TH","0","0","0","0","1","0","90","1"],
  ["19","AIP","11","TH","0","0","0","0","1","0","9999","1"],["20","AIP","9","TH","0","0","0","0","1","0","180","1"],
  ["21","PK","11","TH","0","1","0","0","1","1","9999","0"],["22","PK","16","TH","0","1","0","0","1","1","365","0"],
  ["23","PK","15","TH","0","1","0","0","1","1","180","0"],["24","PK","10","TH","0","1","0","0","1","1","9999","0"],
  ["25","PK","9","TH","0","1","0","0","1","1","365","0"],["26","LM","15","TH","0","0","0","2","4","0","180","0"],
  ["27","LM","10","TH","0","0","0","2","4","0","180","0"],["28","LM","15","TH","0","0","0","2","5","0","180","0"],
  ["29","LM","13","TH","0","0","0","2","3","0","9999","0"],["30","CC","9","TH","0","0","0","8","1","0","180","0"],
  ["31","CC","10","TH","0","0","0","8","1","0","9999","0"],["32","CC","13","TH","0","0","0","8","1","0","9999","0"],
  ["33","CC","11","TH","0","0","0","8","1","0","9999","0"],["34","PA","9","TH","0","0","0","0","1","0","0","0"],
  ["35","PA","10","TH","0","0","0","0","1","0","2","0"],["36","PA","14","TH","0","0","0","0","1","0","1","0"],
  ["37","PA","16","TH","0","0","0","0","1","0","1","0"],["38","BL","14","TH","0","1","0","1","1","1","180","0"],
  ["39","BL","16","TH","0","1","0","1","1","0","365","0"],["40","BL","15","TH","0","1","0","1","1","0","90","0"],
];
kids.push(table(["#","scn","hr","ctry","newC","newD","fail","conc","asub","npk","perm","aip"], SROWS,
  [440, 720, 540, 700, 700, 700, 660, 680, 740, 660, 2060, 760]));

kids.push(h2("12.3 กระบวนการ (Pipeline)"));
kids.push(p("Data Selection/Sampling:", { bold: true }));
kids.push(bullet("รอบ 1: reservoir sampling สตรีม 9 GB → normal 10,000 + ATO 100"));
kids.push(bullet("รอบ 2: 2-pass — หา ATO users + สุ่ม normal users → ดึง login history จริง (cap/user กัน OOM)"));
kids.push(p("Data Cleaning:", { bold: true }));
kids.push(bullet("filter normal สะอาด (ไม่ปน attack-IP/ATO/login fail); True/False → 1/0; parse timestamp + UA→browser family/device; ตัด field รก/parse ไม่ได้"));
kids.push(p("Data Transformation / Feature Engineering:", { bold: true }));
kids.push(bullet("รอบ 1 (23 feat): จริงจาก raw (hour/day/attack_ip) + สังเคราะห์ history/passkey/session"));
kids.push(bullet("รอบ 2 (12 feat จริงล้วน): คำนวณจากประวัติ login จริงต่อ user (O(n) two-pointer); ตัด active_session_count (RBA ไม่มี); cold start <5 → neutral"));
kids.push(bullet("StandardScaler (จำเป็นกับ OCSVM/LOF; IForest invariant)"));
kids.push(p("Model Training:", { bold: true }));
kids.push(bullet("IForest (n=200), OCSVM (RBF, nu≈prevalence), LOF (k=20); 2 โปรโตคอล: in-sample + proper one-class group-by-user; label ไม่ใช้ตอน train"));
kids.push(p("Evaluation:", { bold: true }));
kids.push(bullet("Precision/Recall/F1/ROC-AUC/PR-AUC (หลัก) + Ablation A→B→C + Robustness (multi-seed/Wilcoxon/operating-point) + SHAP"));

// 13. SHAP on OCSVM
kids.push(h1("13. SHAP บน OneClassSVM — เหตุผลที่เลือก IsolationForest"));
kids.push(image("shap_ocsvm_vs_iforest.png", 660));
kids.push(cap("รูป 13.1 — SHAP importance: IForest (TreeExplainer, exact) vs OCSVM (KernelExplainer, approx)"));
kids.push(p("ต้นทุนการอธิบาย (วัดจริง):", { bold: true }));
kids.push(table(["Explainer", "ขอบเขต", "เวลา", "ต่อแถว", "ชนิด"], [
  ["TreeExplainer (IForest)", "ทั้งชุด 10,140 แถว", "31 s", "3.07 ms", "exact"],
  ["KernelExplainer (OCSVM)", "แค่ 300 แถว (bg=30)", "61 s", "203 ms (~66×)", "approximate"],
], [2700, 2600, 1300, 1700, 1060]));
kids.push(bullet("Explainability: SHAP ของ IForest exact + เร็ว (3 ms/แถว) → อธิบายทุก login ใน audit UI ได้จริง; OCSVM ช้า 66× + approx → ทำ real-time ไม่ได้"));
kids.push(bullet("Top-10 overlap (IForest ∩ OCSVM) = แค่ 4/10 → OCSVM ให้ feature สำคัญต่างและไม่นิ่ง อธิบายต่อ auditor ได้ไม่สม่ำเสมอ"));
kids.push(bullet("บนข้อมูลจริง (proper protocol) IForest ≈ OCSVM (0.427 vs 0.414) → detection เสมอกัน; IForest ชนะด้วย explainability + latency + scalability"));
kids.push(p("สรุป: OneClassSVM = comparative upper-bound; IsolationForest = production choice (explainable + เร็ว + สเกลได้ + เสมอกันบนข้อมูลจริง)", { bold: true }));

// Appendices
kids.push(new Paragraph({ children: [new PageBreak()] }));
kids.push(h1("ภาคผนวก A — รูป Experiment A (13 features)"));
["confusion_matrices", "metrics_comparison"].forEach(f => kids.push(image(`A/${f}.png`, 600)));
kids.push(sideBySide("A/roc_curves.png", "A/pr_curves.png", 320));
kids.push(sideBySide("A/shap_feature_importance.png", "A/shap_summary_beeswarm.png", 320));

kids.push(new Paragraph({ children: [new PageBreak()] }));
kids.push(h1("ภาคผนวก B — รูป Experiment B (19 features)"));
["confusion_matrices", "metrics_comparison"].forEach(f => kids.push(image(`B/${f}.png`, 600)));
kids.push(sideBySide("B/roc_curves.png", "B/pr_curves.png", 320));
kids.push(sideBySide("B/shap_feature_importance.png", "B/shap_summary_beeswarm.png", 320));

// ---------- doc ----------
const doc = new Document({
  styles: {
    default: { document: { run: { font: FONT, size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 30, bold: true, font: FONT, color: "1F3864" },
        paragraph: { spacing: { before: 260, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 25, bold: true, font: FONT, color: "2E5A88" },
        paragraph: { spacing: { before: 180, after: 120 }, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [{ reference: "b", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•",
    alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 600, hanging: 300 } } } }] }] },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 },
      margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "หน้า ", size: 16 }), new TextRun({ children: [PageNumber.CURRENT], size: 16 })] })] }) },
    children: kids,
  }],
});

Packer.toBuffer(doc).then(buf => { fs.writeFileSync(OUT, buf); console.log("✅ wrote", OUT, "(", (buf.length / 1024).toFixed(0), "KB )"); });
