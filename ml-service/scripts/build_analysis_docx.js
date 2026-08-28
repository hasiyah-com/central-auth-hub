/* สร้าง Word ใหม่: การวิเคราะห์ RBA — ความหนาแน่น/การแบ่งกลุ่ม + เปรียบเทียบ Forest vs SVM (12 & 23 feat)
 * Run: NODE_PATH="$(npm root -g)" node ml-service/scripts/build_analysis_docx.js [outfile]
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
const OUT = process.argv[2] || path.join(ROOT, "hub", "backend", "tests", "reports", "RBA_Model_Analysis_2026-06-15.docx");
const FONT = "Tahoma";
const CW = 9360;
const HL = "F4D03F";

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
function p(t, o = {}) { return new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text: t, ...o })] }); }
function bullet(t) { return new Paragraph({ numbering: { reference: "b", level: 0 }, spacing: { after: 60 }, children: [new TextRun(t)] }); }
const bd = { style: BorderStyle.SINGLE, size: 1, color: "BBBBBB" };
const borders = { top: bd, bottom: bd, left: bd, right: bd, insideHorizontal: bd, insideVertical: bd };
function cell(text, w, { head = false, bold = false, fill = null, align = AlignmentType.LEFT } = {}) {
  return new TableCell({ width: { size: w, type: WidthType.DXA },
    shading: fill ? { fill, type: ShadingType.CLEAR } : (head ? { fill: "2E5A88", type: ShadingType.CLEAR } : undefined),
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: [new Paragraph({ alignment: align, children: [new TextRun({ text: String(text), bold: head || bold, color: head ? "FFFFFF" : "000000", size: 18 })] })] });
}
function table(headRow, rows, widths) {
  const trs = [new TableRow({ tableHeader: true, children: headRow.map((t, i) => cell(t, widths[i], { head: true, align: i === 0 ? AlignmentType.LEFT : AlignmentType.CENTER })) })];
  for (const r of rows) trs.push(new TableRow({ children: r.map((c, i) => { const o = (c && typeof c === "object") ? c : { v: c }; return cell(o.v, widths[i], { bold: o.bold, fill: o.fill, align: i === 0 ? AlignmentType.LEFT : AlignmentType.CENTER }); }) }));
  return new Table({ width: { size: CW, type: WidthType.DXA }, columnWidths: widths, borders, rows: trs });
}
function sideBySide(relL, relR, w) {
  const noB = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
  const nb = { top: noB, bottom: noB, left: noB, right: noB, insideHorizontal: noB, insideVertical: noB };
  const mk = (rel) => new TableCell({ width: { size: CW / 2, type: WidthType.DXA }, borders: nb, children: [image(rel, w)] });
  return new Table({ width: { size: CW, type: WidthType.DXA }, columnWidths: [CW / 2, CW / 2], borders: nb, rows: [new TableRow({ children: [mk(relL), mk(relR)] })] });
}

const k = [];
// title
k.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 2400, after: 120 }, children: [new TextRun({ text: "การวิเคราะห์ RBA Dataset", bold: true, size: 48 })] }));
k.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 80 }, children: [new TextRun({ text: "ความหนาแน่น · การแบ่งกลุ่ม · เปรียบเทียบ Forest vs SVM", bold: true, size: 32, color: "2E5A88" })] }));
k.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 }, children: [new TextRun({ text: "RBA dataset (Wiefling 2022) · 12 features → 23 features", size: 24, italics: true, color: "555555" })] }));
k.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 40 }, children: [new TextRun({ text: "Central Auth Hub — Senior Project", size: 24 })] }));
k.push(new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "15 มิถุนายน 2026", size: 22 })] }));
k.push(new Paragraph({ children: [new PageBreak()] }));
k.push(new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("สารบัญ")] }));
k.push(new TableOfContents("TOC", { hyperlink: true, headingStyleRange: "1-2" }));
k.push(new Paragraph({ spacing: { after: 60 }, children: [new TextRun({ text: "(เปิดใน Word กด F9 เพื่ออัปเดตเลขหน้า)", italics: true, size: 16, color: "888888" })] }));
k.push(new Paragraph({ children: [new PageBreak()] }));

// intro
k.push(h1("บทนำ — ลำดับการวิเคราะห์"));
k.push(p("เอกสารนี้วิเคราะห์ RBA dataset (Wiefling et al. 2022) ด้วยโมเดล unsupervised 2 ตัวหลัก — IsolationForest (Forest) และ OneClassSVM (SVM) — ตามลำดับ 4 ส่วน:"));
[
  "ส่วน 1: RBA จริง — ดู 'ความหนาแน่น' และ 'การแบ่งกลุ่ม' ของข้อมูล (PCA 2D + การกระจาย anomaly score)",
  "ส่วน 2: เทรนด้วย 12 ฟีเจอร์แรก — เปรียบเทียบ Forest vs SVM",
  "ส่วน 3: ข้อมูลจริง + สร้างความผิดปกติ (synthetic) — ดูการแบ่งกลุ่มอีกครั้ง",
  "ส่วน 4: เทรนด้วย 23 ฟีเจอร์ — ประเมินประสิทธิภาพเต็มรูปแบบ",
].forEach(t => k.push(bullet(t)));
k.push(p("หมายเหตุ: RBA เต็มมี 31.3M logins — การ fit SVM (O(n²)) บนทั้งหมดไม่เป็นไปได้ จึงใช้ sample จริงที่เป็นตัวแทน (normal 10,000 + ATO จริงทั้งหมด 141)", { size: 18, italics: true }));

// ── Part 1 ──
k.push(h1("ส่วน 1: RBA จริง — ความหนาแน่นและการแบ่งกลุ่ม"));
k.push(p("ข้อมูล: RBA จริง 12 features (10,141 แถว, ATO จริง 141 = 1.39%). fit Forest + SVM แล้วดู (ก) PCA 2D — โครงสร้าง/ความหนาแน่น (ข) การกระจาย anomaly score แยก normal/anomaly"));
k.push(table(["โมเดล", "ROC-AUC", "PR-AUC", "F1"], [
  ["IsolationForest", "0.872", "0.079", "0.057"],
  ["OneClassSVM", "0.764", "0.093", "0.156"],
], [3360, 2000, 2000, 2000]));
k.push(p("PCA (PC1+PC2) อธิบายความแปรปรวนได้ 42.9%", { size: 18, italics: true }));
k.push(image("CLUSTER/real12_cluster.png", 660));
k.push(cap("รูป 1.1 — PCA 2D (ซ้าย) + การกระจาย anomaly score ของ Forest/SVM (กลาง/ขวา) บน RBA จริง"));
k.push(h2("อธิบาย"));
k.push(bullet("PCA: normal (น้ำเงิน) เกาะเป็น 'ก้อนหนาแน่น'; anomaly จริง (แดง) ส่วนใหญ่ 'ฝังปน' อยู่ในกลุ่ม normal → แยกยาก (นี่คือเหตุผลที่ ATO จริงตรวจยาก)"));
k.push(bullet("Forest score: แยกเป็น 2 ยอด (bimodal) — anomaly เลื่อนไปฝั่ง score สูง แต่ยัง overlap หางของ normal → ROC 0.872 แต่ PR-AUC ต่ำ (0.079) เพราะ precision ที่จุดบนสุดต่ำ"));
k.push(bullet("SVM score: normal/anomaly 'ทับกันมาก' → แยกได้แย่กว่า (ROC 0.764)"));
k.push(p("สรุปส่วน 1: บนข้อมูลจริง การแบ่งกลุ่มทำได้ยาก — anomaly ไม่แยกออกจากความหนาแน่นของ normal ชัดเจน; Forest แยกได้ดีกว่า SVM", { bold: true }));

// ── Part 2 ──
k.push(new Paragraph({ children: [new PageBreak()] }));
k.push(h1("ส่วน 2: เทรน 12 ฟีเจอร์แรก — เปรียบเทียบ Forest vs SVM"));
k.push(p("12 features = temporal/geo/device/velocity/brute + is_attack_ip (ชุดพื้นฐานที่ derive จาก RBA จริงล้วน). วัด 2 โปรโตคอล: in-sample และ proper (one-class, เทรน normal-only, group-by-user, 10 splits)"));
k.push(table(["โปรโตคอล / โมเดล", "ROC-AUC", "PR-AUC", "F1 / Recall"], [
  [{ v: "in-sample", bold: true }, "", "", ""],
  ["IsolationForest", "0.872", "0.079", "F1 0.057"],
  ["OneClassSVM", "0.764", "0.093", "F1 0.156"],
  [{ v: "proper split (generalization)", bold: true }, "", "", ""],
  [{ v: "IsolationForest", bold: true }, "0.890 ± 0.041", { v: "0.427 ± 0.166", fill: HL, bold: true }, "R 0.265"],
  ["OneClassSVM", "0.839 ± 0.028", "0.414 ± 0.164", "R 0.500"],
], [3360, 2200, 2200, 1600]));
k.push(cap("ตาราง 2.1 — Forest vs SVM บน 12 ฟีเจอร์ (จริง)"));
k.push(sideBySide("REAL/roc_curves.png", "REAL/pr_curves.png", 330));
k.push(cap("รูป 2.1 — ROC (ซ้าย) และ Precision-Recall (ขวา) บน 12 ฟีเจอร์"));
k.push(h2("อธิบาย"));
k.push(bullet("in-sample: PR-AUC ต่ำมากทั้งคู่ (0.08–0.09) — ยืนยันว่า ATO จริงบน 12 feature แยกยาก"));
k.push(bullet("proper split: PR-AUC สูงขึ้น (0.42–0.43) เพราะเทรน normal-only สะอาด (ไม่ปน attack); ROC-AUC เทียบได้ ~0.89"));
k.push(bullet("Forest ≈ SVM (0.427 vs 0.414, std ทับกัน) — บนข้อมูลจริงสองโมเดลเสมอกัน"));

// ── Part 3 ──
k.push(new Paragraph({ children: [new PageBreak()] }));
k.push(h1("ส่วน 3: ข้อมูลจริง + สร้างความผิดปกติ — การแบ่งกลุ่ม"));
k.push(p("ข้อมูล: normal จริง + ATO จริง + synthetic attack (23 features, 10,140 แถว, attack 1.38%). ดู PCA + score distribution เทียบกับส่วน 1 เพื่อดูว่า 'synthetic anomaly แยกกลุ่มง่ายขึ้นไหม'"));
k.push(table(["โมเดล", "ROC-AUC", "PR-AUC", "F1"], [
  ["IsolationForest", "0.928", "0.734", "0.707"],
  [{ v: "OneClassSVM", bold: true }, "0.963", { v: "0.844", fill: HL, bold: true }, "0.750"],
], [3360, 2000, 2000, 2000]));
k.push(p("PCA (PC1+PC2) = 21.9% (23 มิติกระจายมากขึ้น)", { size: 18, italics: true }));
k.push(image("CLUSTER/synth23_cluster.png", 660));
k.push(cap("รูป 3.1 — PCA 2D + score distribution บนชุดจริง+synthetic (23 features)"));
k.push(h2("อธิบาย"));
k.push(bullet("score distribution: normal/anomaly 'แยกกลุ่มชัดกว่าส่วน 1 มาก' — synthetic attack ถูกออกแบบให้มีสัญญาณเด่น → PR-AUC พุ่งเป็น 0.73–0.84"));
k.push(bullet("PCA อธิบายความแปรปรวนน้อยลง (21.9%) เพราะมี 23 มิติ (ข้อมูลกระจายในมิติสูง) — anomaly แยกได้ดีในมิติเต็ม แม้ภาพ 2D จะดูปนกัน"));
k.push(p("สรุปส่วน 3: เทียบส่วน 1 — synthetic anomaly 'แยกกลุ่มง่ายกว่า ATO จริงมาก' (PR-AUC 0.73–0.84 vs 0.08–0.09) → ตัวเลข synthetic ดูดีเกินจริง ต้องระวังการตีความ", { bold: true }));

// ── Part 4 ──
k.push(new Paragraph({ children: [new PageBreak()] }));
k.push(h1("ส่วน 4: เทรน 23 ฟีเจอร์ — ประเมินประสิทธิภาพ"));
k.push(p("23 features (Experiment C) = 12 พื้นฐาน + Tier-1 (session/scope/permission) + Passkey. เทรน 3 โมเดลเทียบเต็มรูปแบบ (in-sample @ prevalence 1.38%)"));
k.push(table(["โมเดล", "Precision", "Recall", "F1", "ROC-AUC", "PR-AUC"], [
  ["IsolationForest", "0.707", "0.707", "0.707", "0.928", "0.734"],
  [{ v: "OneClassSVM", bold: true }, "0.609", "0.836", "0.705", "0.963", { v: "0.844", fill: HL, bold: true }],
  ["LocalOutlierFactor", "0.500", "0.500", "0.500", "0.751", "0.536"],
], [2600, 1360, 1360, 1360, 1360, 1320]));
k.push(cap("ตาราง 4.1 — ผล 3 โมเดล บน 23 ฟีเจอร์"));
k.push(image("C/metrics_comparison.png", 600));
k.push(cap("รูป 4.1 — เปรียบเทียบ metrics (23 features)"));
k.push(image("C/confusion_matrices.png", 640));
k.push(cap("รูป 4.2 — Confusion matrices (23 features)"));
k.push(sideBySide("C/roc_curves.png", "C/pr_curves.png", 330));
k.push(cap("รูป 4.3 — ROC และ PR curves (23 features)"));
k.push(image("ablation_pr_auc.png", 620));
k.push(cap("รูป 4.4 — Ablation: PR-AUC/F1 เมื่อเพิ่ม feature 13→19→23"));
k.push(h2("อธิบาย"));
k.push(bullet("23 feature ให้ผลดีที่สุด — OCSVM เด่นสุด (PR-AUC 0.844, ROC 0.963); IForest รองลงมา (PR 0.734) แต่เสถียร+อธิบายได้ (SHAP)"));
k.push(bullet("Ablation: การเพิ่ม Tier-1 (13→19) และ Passkey (19→23) ช่วยเพิ่ม PR-AUC/Recall ตามลำดับ"));

// ── สรุป ──
k.push(new Paragraph({ children: [new PageBreak()] }));
k.push(h1("สรุปรวม"));
k.push(table(["มุมมอง", "RBA จริง 12 feat", "จริง+synthetic 23 feat"], [
  ["การแบ่งกลุ่ม (PCA)", "anomaly ฝังปน normal — แยกยาก", "แยกกลุ่มชัดกว่า"],
  ["Forest PR-AUC", "0.079 (in-sample) / 0.427 (proper)", "0.734"],
  ["SVM PR-AUC", "0.093 / 0.414", "0.844"],
  ["ตัวชนะ", "Forest ≈ SVM (เสมอ)", "SVM > Forest"],
], [2600, 3380, 3380]));
k.push(bullet("บนข้อมูลจริง ATO แยกยาก (anomaly ปนใน density ของ normal) — PR-AUC ต่ำ, Forest≈SVM"));
k.push(bullet("การเพิ่ม feature (12→23) + synthetic anomaly ทำให้การแบ่งกลุ่มดีขึ้นมาก แต่ตัวเลข synthetic ประเมินเกินจริง — ต้องรายงานคู่กับผลจริง"));
k.push(bullet("เลือกใช้จริง: IsolationForest (explainable + เสถียร + เสมอ SVM บนข้อมูลจริง); OneClassSVM = upper-bound เชิงประสิทธิภาพ"));

const doc = new Document({
  styles: {
    default: { document: { run: { font: FONT, size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 30, bold: true, font: FONT, color: "1F3864" }, paragraph: { spacing: { before: 260, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 25, bold: true, font: FONT, color: "2E5A88" }, paragraph: { spacing: { before: 180, after: 120 }, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [{ reference: "b", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 600, hanging: 300 } } } }] }] },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "หน้า ", size: 16 }), new TextRun({ children: [PageNumber.CURRENT], size: 16 })] })] }) },
    children: k,
  }],
});
Packer.toBuffer(doc).then(buf => { fs.writeFileSync(OUT, buf); console.log("✅ wrote", OUT, "(", (buf.length / 1024).toFixed(0), "KB )"); });
