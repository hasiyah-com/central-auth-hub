<?php
// ============================================================
// index.php — หน้า login
// Compare with old: 156 lines → now 8 lines
// ============================================================
require __DIR__ . '/../vendor/autoload.php';

use CentralAuthHub\Client;

$hub = new Client(require __DIR__ . '/config.php');

if ($hub->isAuthenticated()) {
    header('Location: dashboard.php');
    exit;
}
?>
<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="UTF-8" />
  <title>Subsystem — Login</title>
  <style>
    body { font-family: system-ui; background: #0a0a0f; color: #e8e8f0;
           min-height: 100vh; display: flex; align-items: center; justify-content: center; }
    .card { background: #12121a; border: 1px solid #2a2a3a; border-radius: 16px;
            padding: 40px; max-width: 400px; }
    .btn  { display: block; padding: 14px 24px; background: #6c63ff; color: white;
            text-decoration: none; border-radius: 10px; font-weight: bold; text-align: center; }
    .btn:hover { background: #8b5cf6; }
  </style>
</head>
<body>
  <div class="card">
    <h1>เข้าสู่ระบบผ่าน Hub</h1>
    <p>ใช้ Central Auth Hub จัดการ identity — ไม่ต้องมีรหัสผ่านแยก</p>
    <a href="login.php" class="btn">🔐 Login with Hub</a>
  </div>
</body>
</html>
