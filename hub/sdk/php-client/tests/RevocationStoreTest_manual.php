<?php
// Manual standalone test — RevocationStore + WebhookReceiver
// รัน: E:\xampp\php\php.exe <thisfile>
require __DIR__ . '/../vendor/autoload.php';

use CentralAuthHub\RevocationStore;
use CentralAuthHub\WebhookReceiver;

$tmp = sys_get_temp_dir() . '/revtest_' . uniqid() . '.json';
$s = new RevocationStore($tmp);
$pass = 0;
$total = 0;
function chk(string $name, bool $cond): void
{
    global $pass, $total;
    $total++;
    if ($cond) {
        $pass++;
        echo "  [PASS] $name\n";
    } else {
        echo "  [FAIL] $name\n";
    }
}

// T1-T3 — per-user
$s->markUser('u-1', 1000);
chk('T1 user revoked(1000) > login(900) -> true', $s->isRevokedSince('u-1', 900) === true);
chk('T2 login(1100) > revoke(1000) -> false', $s->isRevokedSince('u-1', 1100) === false);
chk('T3 user khon uen -> false', $s->isRevokedSince('u-2', 900) === false);

// T4-T5 — markAll (config change kicks everyone)
$s->markAll(2000);
chk('T4 markAll(2000) -> u-2 login(1500) -> true', $s->isRevokedSince('u-2', 1500) === true);
chk('T5 markAll(2000) -> login(2500) -> false', $s->isRevokedSince('u-2', 2500) === false);

// T6 — webhook verify OK
$key = 'testkey';
$body = json_encode(['event' => 'access_updated', 'hub_user_id' => 'u-9', 'reason' => 'role_changed']);
$sig = hash_hmac('sha256', $body, $key);
$ts = (string) time();
$payload = WebhookReceiver::verify($key, 300, $body, ['x-hub-signature-256' => $sig, 'x-hub-timestamp' => $ts]);
chk('T6 webhook verify OK -> event=access_updated', ($payload['event'] ?? '') === 'access_updated');

// T7 — bad signature -> throw
try {
    WebhookReceiver::verify($key, 300, $body, ['x-hub-signature-256' => 'bad', 'x-hub-timestamp' => $ts]);
    chk('T7 bad sig -> throw', false);
} catch (\Exception $e) {
    chk('T7 bad sig -> throw', true);
}

// T8 — replay (old timestamp) -> throw
try {
    $oldTs = (string) (time() - 9999);
    WebhookReceiver::verify($key, 300, $body, ['x-hub-signature-256' => $sig, 'x-hub-timestamp' => $oldTs]);
    chk('T8 old timestamp -> throw', false);
} catch (\Exception $e) {
    chk('T8 old timestamp -> throw', true);
}

@unlink($tmp);
echo "\nRESULT: $pass/$total passed\n";
exit($pass === $total ? 0 : 1);
