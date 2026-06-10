<?php
// ============================================================
// dashboard.php — แสดงข้อมูล user
// ============================================================
require __DIR__ . '/../vendor/autoload.php';

use CentralAuthHub\Client;

$hub = new Client(require __DIR__ . '/config.php');

if (!$hub->isAuthenticated()) {
    header('Location: index.php');
    exit;
}

$user = $hub->user();
?>
<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="UTF-8" />
  <title>Dashboard</title>
  <style>
    body { font-family: system-ui; padding: 40px; max-width: 600px; margin: auto; }
    .label { color: #888; font-size: 12px; text-transform: uppercase; }
    .value { font-weight: bold; font-size: 16px; margin-bottom: 12px; }
    a { color: #6c63ff; }
  </style>
</head>
<body>
  <h1>ยินดีต้อนรับ <?= htmlspecialchars($user['name'] ?? $user['email'] ?? '?') ?></h1>

  <div class="label">Email</div>
  <div class="value"><?= htmlspecialchars($user['email'] ?? '—') ?></div>

  <div class="label">Role in subsystem</div>
  <div class="value"><?= htmlspecialchars($user['role_in_subsystem'] ?? '—') ?></div>

  <div class="label">Student ID</div>
  <div class="value"><?= htmlspecialchars($user['student_id'] ?? '—') ?></div>

  <div class="label">Faculty</div>
  <div class="value"><?= htmlspecialchars($user['faculty'] ?? '—') ?></div>

  <div class="label">Token expires</div>
  <div class="value"><?= isset($user['exp']) ? date('Y-m-d H:i:s', $user['exp']) : '—' ?></div>

  <p><a href="logout.php">ออกจากระบบ</a></p>
</body>
</html>
