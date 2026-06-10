<?php

declare(strict_types=1);

namespace CentralAuthHub;

use CentralAuthHub\Exception\HubException;

/**
 * Verify HMAC-SHA256 signed webhook from Hub (back-channel).
 *
 * Headers:
 *   X-Hub-Signature-256: hex(HMAC-SHA256(shared_key, raw_body))
 *   X-Hub-Timestamp:     epoch seconds (replay protection)
 *   X-Hub-Event:         e.g. "access_revoked"
 *
 * Uses hash_equals (constant-time comparison) — กัน timing attack
 */
final class WebhookReceiver
{
    /**
     * Verify signed webhook + return parsed payload.
     *
     * @param string $sharedKey  ตรงกับ WEBHOOK_SHARED_KEY ของ Hub
     * @param int    $maxAgeSec  ไม่รับถ้า timestamp ห่างเกินค่านี้ (default 300s)
     * @return array<string,mixed>
     * @throws HubException
     */
    public static function verify(
        string $sharedKey,
        int $maxAgeSec = 300,
        ?string $rawBody = null,
        ?array $headers = null
    ): array {
        $rawBody = $rawBody ?? file_get_contents('php://input') ?: '';
        $headers = $headers ?? self::normalizeHeaders($_SERVER);

        $sig = $headers['x-hub-signature-256'] ?? '';
        $ts  = $headers['x-hub-timestamp']     ?? '';

        if ($sig === '' || $ts === '') {
            throw new HubException('Missing X-Hub-Signature-256 or X-Hub-Timestamp');
        }

        // Replay protection
        $tsInt = (int) $ts;
        if (abs(time() - $tsInt) > $maxAgeSec) {
            throw new HubException("Webhook timestamp out of tolerance ($maxAgeSec sec)");
        }

        $expected = hash_hmac('sha256', $rawBody, $sharedKey);
        if (!hash_equals($expected, $sig)) {
            throw new HubException('Webhook signature mismatch');
        }

        $payload = json_decode($rawBody, true);
        if (!is_array($payload)) {
            throw new HubException('Webhook body is not valid JSON');
        }
        return $payload;
    }

    /** @return array<string,string> lower-cased header names */
    private static function normalizeHeaders(array $server): array
    {
        $out = [];
        foreach ($server as $k => $v) {
            if (str_starts_with($k, 'HTTP_')) {
                $name = strtolower(str_replace('_', '-', substr($k, 5)));
                $out[$name] = (string) $v;
            }
        }
        return $out;
    }
}
