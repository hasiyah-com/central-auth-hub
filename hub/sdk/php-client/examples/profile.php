<?php
// ============================================================
// profile.php — แสดงทุก field ที่ Hub ส่งมาใน JWT
// ใช้ตรวจ "data minimization" — field ไหนได้รับ (อยู่ใน scope) vs ไม่ได้รับ
// คัดลอกไป C:\xampp\htdocs\myapp\profile.php (แก้ path autoload ตามที่วาง)
// ============================================================
require __DIR__ . '/../vendor/autoload.php';

use CentralAuthHub\Client;

$hub = new Client(require __DIR__ . '/config.php');
if (!$hub->isAuthenticated()) {
    header('Location: index.php');
    exit;
}

$claims = $hub->user();              // JWT claims ที่ verify แล้ว
$token  = $hub->accessToken();

// ── field ทั้งหมดที่ Hub "อาจ" ส่ง ตาม scope (ตรงกับหน้าลงทะเบียน) ──
// [claim_key, label, scope_name, หมายเหตุ]
$DATA_FIELDS = [
    ['email',       'Email',        'email',       'อีเมลของผู้ใช้'],
    ['name',        'Full Name',    'name',        'ชื่อ-นามสกุล'],
    ['student_id',  'Student ID',   'student_id',  'รหัสนักศึกษา (เฉพาะนักศึกษา)'],
    ['employee_id', 'Employee ID',  'employee_id', 'รหัสบุคลากร'],
    ['faculty',     'Faculty',      'faculty',     'คณะ'],
    ['major',       'Major',        'major',       'สาขาวิชา'],
    ['year',        'Year',         'year',        'ชั้นปี (เฉพาะนักศึกษา)'],
    ['position',    'Position',     'position',    'ตำแหน่ง (เฉพาะบุคลากร)'],
    ['phone',       'Phone',        'phone',       'เบอร์โทรศัพท์'],
    ['address',     'Address',      'address',     'ที่อยู่'],
];

// ── JWT meta claims (มาเสมอ ไม่ขึ้นกับ scope) ──
$META_FIELDS = [
    ['sub',                'Subject (user id)'],
    ['aud',                'Audience (client_id)'],
    ['iss',                'Issuer'],
    ['role_in_subsystem',  'Role ในระบบนี้'],
    ['jti',                'JWT ID'],
];

$received = 0;
foreach ($DATA_FIELDS as $f) {
    if (isset($claims[$f[0]]) && $claims[$f[0]] !== null && $claims[$f[0]] !== '') {
        $received++;
    }
}
$total = count($DATA_FIELDS);

function h($v): string { return htmlspecialchars((string)$v, ENT_QUOTES, 'UTF-8'); }
function fmtTime($ts): string {
    if (!$ts) return '—';
    return date('Y-m-d H:i:s', (int)$ts) . ' (' . date_default_timezone_get() . ')';
}
$exp = $claims['exp'] ?? null;
$expLeft = $exp ? max(0, (int)$exp - time()) : null;
?>
<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Profile — ตรวจข้อมูลที่ได้รับจาก Hub</title>
<style>
  :root { --brand:#4f46e5; --good:#16a34a; --muted:#94a3b8; --bg:#f8fafc; --card:#fff; --ink:#0f172a; --line:#e2e8f0; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); font-family:'Segoe UI','Sarabun',sans-serif; color:var(--ink); padding:32px 16px; }
  .wrap { max-width:920px; margin:0 auto; }
  h1 { font-size:22px; margin:0 0 4px; }
  .sub { color:var(--muted); font-size:13px; margin-bottom:20px; }
  .summary { display:flex; gap:12px; align-items:center; background:var(--card); border:1px solid var(--line);
             border-radius:14px; padding:16px 20px; margin-bottom:20px; }
  .summary .big { font-size:28px; font-weight:800; color:var(--brand); }
  .grid { display:grid; grid-template-columns:repeat(2,1fr); gap:12px; }
  @media(max-width:640px){ .grid{ grid-template-columns:1fr; } }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; position:relative; }
  .card.on { border-color:#c7d2fe; background:#f5f3ff; }
  .card.off { opacity:.6; }
  .label { font-weight:700; font-size:14px; }
  .scope { font-family:ui-monospace,monospace; font-size:11px; color:var(--muted); margin-left:6px; }
  .note { font-size:11px; color:var(--muted); margin-top:2px; }
  .val { margin-top:8px; font-size:14px; word-break:break-all; }
  .val.has { color:var(--ink); font-weight:600; }
  .val.miss { color:var(--muted); font-style:italic; }
  .badge { position:absolute; top:12px; right:14px; font-size:11px; font-weight:700; padding:2px 8px; border-radius:999px; }
  .badge.on { background:#dcfce7; color:var(--good); }
  .badge.off { background:#f1f5f9; color:var(--muted); }
  .section { margin-top:28px; font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); margin-bottom:10px; }
  table.meta { width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:12px; overflow:hidden; }
  table.meta td { padding:10px 14px; border-bottom:1px solid var(--line); font-size:13px; }
  table.meta td:first-child { color:var(--muted); width:200px; }
  table.meta td:last-child { font-family:ui-monospace,monospace; word-break:break-all; }
  table.meta tr:last-child td { border-bottom:none; }
  details { margin-top:20px; background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
  summary { cursor:pointer; font-weight:600; color:var(--brand); }
  pre { background:#0f172a; color:#e2e8f0; padding:14px; border-radius:8px; overflow:auto; font-size:12px; margin-top:10px; }
  .actions { margin-top:24px; }
  a.btn { display:inline-block; padding:9px 16px; border-radius:9px; text-decoration:none; font-size:14px; }
  a.logout { background:#fee2e2; color:#b91c1c; }
</style>
</head>
<body>
<div class="wrap">
  <h1>👤 โปรไฟล์ผู้ใช้ — ข้อมูลที่ได้รับจาก Hub</h1>
  <div class="sub">หน้านี้แสดงทุก field เพื่อตรวจว่า scope ที่ขอ → ได้ข้อมูลครบไหม (data minimization)</div>

  <div class="summary">
    <div class="big"><?= $received ?>/<?= $total ?></div>
    <div>
      <div style="font-weight:700">field ที่ได้รับจริง</div>
      <div class="sub" style="margin:0">Hub ใส่เฉพาะ field ใน scope ที่ subsystem ขอ — field นอก scope จะไม่มาเลย (privacy by design)</div>
    </div>
  </div>

  <div class="grid">
    <?php foreach ($DATA_FIELDS as [$key,$label,$scope,$note]):
        $has = isset($claims[$key]) && $claims[$key] !== null && $claims[$key] !== ''; ?>
      <div class="card <?= $has ? 'on' : 'off' ?>">
        <span class="badge <?= $has ? 'on' : 'off' ?>"><?= $has ? '✓ ได้รับ' : '— ไม่มา' ?></span>
        <div class="label"><?= h($label) ?><span class="scope"><?= h($scope) ?></span></div>
        <div class="note"><?= h($note) ?></div>
        <div class="val <?= $has ? 'has' : 'miss' ?>">
          <?= $has ? h($claims[$key]) : 'ไม่ได้รับ (ไม่อยู่ใน scope หรือ user ไม่มีข้อมูลนี้)' ?>
        </div>
      </div>
    <?php endforeach; ?>
  </div>

  <div class="section">JWT Metadata (มาเสมอ)</div>
  <table class="meta">
    <?php foreach ($META_FIELDS as [$key,$label]): ?>
      <tr><td><?= h($label) ?></td><td><?= isset($claims[$key]) ? h($claims[$key]) : '—' ?></td></tr>
    <?php endforeach; ?>
    <tr><td>Issued at (iat)</td><td><?= fmtTime($claims['iat'] ?? null) ?></td></tr>
    <tr><td>Expires (exp)</td><td><?= fmtTime($exp) ?> · เหลือ <?= $expLeft !== null ? $expLeft.' วินาที' : '—' ?></td></tr>
  </table>

  <details>
    <summary>🔍 ดู raw JWT claims (debug)</summary>
    <pre><?= h(json_encode($claims, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)) ?></pre>
    <div class="note" style="margin-top:8px">access_token (JWT ดิบ) — เอาไป decode ดูที่ jwt.io ได้:</div>
    <pre style="font-size:11px"><?= h($token) ?></pre>
  </details>

  <div class="actions">
    <a class="btn logout" href="logout.php">ออกจากระบบ</a>
  </div>
</div>
</body>
</html>
