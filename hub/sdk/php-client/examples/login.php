<?php
// ============================================================
// login.php — เริ่ม OAuth flow (PKCE + state + redirect)
// 3 lines.
// ============================================================
require __DIR__ . '/../vendor/autoload.php';

use CentralAuthHub\Client;

$hub = new Client(require __DIR__ . '/config.php');
$hub->startLogin('/subsystem/dashboard.php');
