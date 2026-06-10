<?php
// ============================================================
// callback.php — รับ code → verify → set session
// Compare with old: 100+ lines → now 13 lines (including error handling).
// ============================================================
require __DIR__ . '/../vendor/autoload.php';

use CentralAuthHub\Client;
use CentralAuthHub\Exception\HubException;

$hub = new Client(require __DIR__ . '/config.php');

try {
    $result = $hub->handleCallback();
    // SDK เก็บ session ให้แล้ว — แค่ redirect ต่อ
    header('Location: ' . ($result['return_path'] ?? 'dashboard.php'));
    exit;
} catch (HubException $e) {
    http_response_code(400);
    echo '<h1>Login failed</h1><p>' . htmlspecialchars($e->getMessage()) . '</p>';
}
