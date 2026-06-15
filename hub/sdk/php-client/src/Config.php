<?php

declare(strict_types=1);

namespace CentralAuthHub;

use CentralAuthHub\Exception\HubException;

/**
 * Config — validate + hold SDK settings.
 */
final class Config
{
    public string $hubUrl;
    public string $clientId;
    public string $clientSecret;
    public string $redirectUri;
    /** @var string[] */
    public array $scope;
    public int $jwksCacheTtl;
    public int $httpTimeout;
    public string $sessionKey;
    /** อายุ session สูงสุด (วินาที) — 0 = ใช้ JWT exp อย่างเดียว (เหมือน dorm max_age) */
    public int $sessionMaxAge;
    /** shared key สำหรับ verify webhook จาก Hub (ตรงกับ WEBHOOK_SHARED_KEY) */
    public string $webhookSharedKey;
    /** path ไฟล์ revocation store — set เพื่อเปิด real-time re-auth (access_updated/revoked) */
    public string $revocationStorePath;

    /**
     * @param array{
     *   hub_url: string,
     *   client_id: string,
     *   client_secret: string,
     *   redirect_uri: string,
     *   scope?: string[],
     *   jwks_cache_ttl?: int,
     *   http_timeout?: int,
     *   session_key?: string,
     *   session_max_age?: int,
     * } $opts
     */
    public function __construct(array $opts)
    {
        foreach (['hub_url', 'client_id', 'client_secret', 'redirect_uri'] as $req) {
            if (empty($opts[$req])) {
                throw new HubException("Config: missing required key '$req'");
            }
        }
        $this->hubUrl       = rtrim($opts['hub_url'], '/');
        $this->clientId     = $opts['client_id'];
        $this->clientSecret = $opts['client_secret'];
        $this->redirectUri  = $opts['redirect_uri'];
        $this->scope        = $opts['scope']        ?? ['openid', 'profile', 'email'];
        $this->jwksCacheTtl = $opts['jwks_cache_ttl'] ?? 600;
        $this->httpTimeout  = $opts['http_timeout']  ?? 10;
        // namespace ใน $_SESSION เพื่อแยกจาก session อื่นของ app
        $this->sessionKey   = $opts['session_key']   ?? 'cah';
        // 0 = ปิด (ใช้ JWT exp อย่างเดียว); > 0 = บังคับ re-login หลัง N วินาที
        // (เหมือน dorm session_max_age_seconds — session สั้นลง → pick up scope ใหม่เร็วขึ้น)
        $this->sessionMaxAge = (int) ($opts['session_max_age'] ?? 0);
        $this->webhookSharedKey = (string) ($opts['webhook_shared_key'] ?? '');
        // ปล่อยว่าง = ปิด real-time revoke check (ใช้แค่ session_max_age/exp)
        $this->revocationStorePath = (string) ($opts['revocation_store_path'] ?? '');
    }
}
