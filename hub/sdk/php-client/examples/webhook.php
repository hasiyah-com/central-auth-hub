<?php
// ============================================================
// webhook.php — รับ event จาก Hub (access_revoked ฯลฯ)
// 8 lines. Compare with old: 40+ lines of HMAC verify
// ============================================================
require __DIR__ . '/../vendor/autoload.php';

use CentralAuthHub\WebhookReceiver;
use CentralAuthHub\Exception\HubException;

// ใส่ SHARED_KEY ที่ตรงกับ Hub's WEBHOOK_SHARED_KEY ใน env
$sharedKey = getenv('HUB_WEBHOOK_SHARED_KEY') ?: '';

try {
    $payload = WebhookReceiver::verify($sharedKey, maxAgeSec: 300);
} catch (HubException $e) {
    http_response_code(401);
    exit($e->getMessage());
}

// process event
$event   = $payload['event']        ?? '';
$userId  = $payload['hub_user_id']  ?? '';

if ($event === 'access_revoked' && $userId) {
    // dev: ลบ user session / mark resident.hub_access_revoked_at ฯลฯ
    // pdo->prepare(...)->execute([$userId]);
}

header('Content-Type: application/json');
echo json_encode(['status' => 'ok']);
