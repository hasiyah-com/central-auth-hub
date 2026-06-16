<?php

declare(strict_types=1);

namespace CentralAuthHub;

use CentralAuthHub\Exception\HubException;

/**
 * Central Auth Hub PHP Client — main facade.
 *
 * 5 บรรทัดเสร็จ flow ทั้งหมด:
 *   $hub = new Client([...]);
 *   $hub->startLogin();          // หน้า login
 *   $user = $hub->handleCallback();  // callback.php
 *   $hub->logout();              // logout.php
 */
final class Client
{
    public Config $config;
    private Discovery $discovery;
    private TokenExchange $tokenExchange;
    private JwtVerifier $jwtVerifier;

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
     * } $opts
     */
    public function __construct(array $opts)
    {
        $this->config        = new Config($opts);
        $this->discovery     = new Discovery($this->config);
        $this->tokenExchange = new TokenExchange($this->config, $this->discovery);
        $this->jwtVerifier   = new JwtVerifier($this->config, $this->discovery);
        $this->ensureSession();
    }

    /**
     * Start OAuth login — สร้าง PKCE + state, เก็บ session, redirect.
     *
     * @param string|null $returnPath path ภายในแอพที่จะกลับหลัง login (เก็บใน session)
     * @param bool $sendRedirect ตั้ง false ถ้าอยาก get URL กลับมาเองเพื่อ test
     * @return string the authorize URL (เผื่อ debug)
     */
    public function startLogin(?string $returnPath = null, bool $sendRedirect = true): string
    {
        $this->ensureSession();
        // กัน open redirect / header injection — รับเฉพาะ relative path ภายในแอป
        // reject: absolute URL (scheme:// หรือ //host), backslash, CR/LF
        // (เผื่อ dev เผลอส่ง user input เช่น startLogin($_GET['next']))
        $returnPath = self::sanitizeReturnPath($returnPath);
        $disc = $this->discovery->get();
        $authorize = $disc['authorization_endpoint'] ?? null;
        if (!$authorize) {
            throw new HubException('Discovery missing authorization_endpoint');
        }

        $verifier = PkceHelper::generateVerifier();
        $challenge = PkceHelper::challengeFor($verifier);
        $state = StateHelper::generate();

        // เก็บใน session — verify ตอน callback
        $_SESSION[$this->config->sessionKey] = array_merge(
            $_SESSION[$this->config->sessionKey] ?? [],
            [
                'state'         => $state,
                'code_verifier' => $verifier,
                'return_path'   => $returnPath,
            ]
        );

        $params = [
            'client_id'             => $this->config->clientId,
            'redirect_uri'          => $this->config->redirectUri,
            'response_type'         => 'code',
            'scope'                 => implode(' ', $this->config->scope),
            'state'                 => $state,
            'code_challenge'        => $challenge,
            'code_challenge_method' => 'S256',
        ];
        $url = $authorize . '?' . http_build_query($params);

        if ($sendRedirect) {
            // PHP-CLI ไม่มี header() — guard ไว้
            if (!headers_sent()) {
                header('Location: ' . $url);
            }
            // ไม่ exit ใน CLI — ให้ caller ตัดสินใจ
            if (PHP_SAPI !== 'cli') {
                exit;
            }
        }
        return $url;
    }

    /**
     * Handle callback — verify state + exchange code + verify JWT.
     *
     * @return array{
     *   claims: array<string,mixed>,
     *   access_token: string,
     *   return_path: ?string,
     * }
     * @throws HubException
     */
    public function handleCallback(?array $query = null): array
    {
        $this->ensureSession();
        $q = $query ?? $_GET;

        if (!empty($q['error'])) {
            throw new HubException('Hub returned error: ' . (string) $q['error']);
        }

        $code  = (string) ($q['code']  ?? '');
        $state = (string) ($q['state'] ?? '');
        if ($code === '' || $state === '') {
            throw new HubException('Missing code or state in callback');
        }

        // verify CSRF state
        StateHelper::verifyAndConsume($this->config->sessionKey, $state);

        // อ่าน code_verifier ที่เก็บไว้
        $verifier = $_SESSION[$this->config->sessionKey]['code_verifier'] ?? '';
        if (!$verifier) {
            throw new HubException('No PKCE verifier in session');
        }
        unset($_SESSION[$this->config->sessionKey]['code_verifier']);

        // exchange code → token
        $tokenResp = $this->tokenExchange->exchange($code, $verifier);
        $accessToken = (string) $tokenResp['access_token'];

        // verify JWT signature/aud/iss/exp
        $claims = $this->jwtVerifier->verify($accessToken);

        // เก็บ session
        $_SESSION[$this->config->sessionKey]['user']         = $claims;
        $_SESSION[$this->config->sessionKey]['access_token'] = $accessToken;
        $_SESSION[$this->config->sessionKey]['logged_in_at'] = time();

        $returnPath = $_SESSION[$this->config->sessionKey]['return_path'] ?? null;
        unset($_SESSION[$this->config->sessionKey]['return_path']);

        return [
            'claims'       => $claims,
            'access_token' => $accessToken,
            'return_path'  => $returnPath,
        ];
    }

    /** Return current logged-in user claims, or null if not logged in. */
    public function user(): ?array
    {
        $this->ensureSession();
        return $_SESSION[$this->config->sessionKey]['user'] ?? null;
    }

    /** Return current access token, or null. */
    public function accessToken(): ?string
    {
        $this->ensureSession();
        return $_SESSION[$this->config->sessionKey]['access_token'] ?? null;
    }

    /**
     * True ถ้า user login อยู่ **และ session ยังไม่หมดอายุ**.
     *
     * บังคับหมดอายุเหมือน dorm (session.py max_age):
     *   1. JWT exp claim — token หมด (default 60 นาที) → false → ต้อง login ใหม่
     *      → login ใหม่ = ได้ JWT ใหม่ที่มี scope ปัจจุบัน (pick up scope ที่เพิ่ง add)
     *   2. session_max_age (ถ้าตั้ง) — บังคับ re-login เร็วขึ้น (เช่น 300 = 5 นาที)
     *
     * หมดอายุ → ล้าง session อัตโนมัติ → หน้า protected เด้งไป login.
     */
    public function isAuthenticated(): bool
    {
        $claims = $this->user();
        if ($claims === null) {
            return false;
        }

        $now = time();

        // (1) JWT exp — token หมดอายุ → session ใช้ไม่ได้
        $exp = (int) ($claims['exp'] ?? 0);
        if ($exp > 0 && $now >= $exp) {
            $this->logout();
            return false;
        }

        $loggedInAt = (int) ($_SESSION[$this->config->sessionKey]['logged_in_at'] ?? 0);

        // (2) session_max_age — บังคับ re-login เร็วขึ้นกว่า JWT exp (optional)
        $maxAge = $this->config->sessionMaxAge;
        if ($maxAge > 0 && $loggedInAt > 0 && $now >= $loggedInAt + $maxAge) {
            $this->logout();
            return false;
        }

        // (3) real-time revoke/update — Hub webhook (access_revoked/access_updated)
        // mark user/all ใน RevocationStore → ถ้า revoke หลัง logged_in_at = ต้อง re-auth
        // (เหมือนหอพัก hub_access_revoked_at — role/scope เปลี่ยน → เด้งทันที)
        $storePath = $this->config->revocationStorePath;
        if ($storePath !== '' && $loggedInAt > 0) {
            $sub = (string) ($claims['sub'] ?? '');
            if ($sub !== '') {
                $store = new RevocationStore($storePath);
                if ($store->isRevokedSince($sub, $loggedInAt)) {
                    $this->logout();
                    return false;
                }
            }
        }

        return true;
    }

    /**
     * Logout — ล้าง session ของ SDK
     * (Hub-side session ของ Google ไม่ได้แตะ — return false-positive on next /oauth/authorize ถ้า Google ยังจำได้)
     */
    public function logout(bool $sendRedirect = false, ?string $returnTo = null): void
    {
        $this->ensureSession();
        unset($_SESSION[$this->config->sessionKey]);

        if ($sendRedirect && $returnTo) {
            if (!headers_sent()) {
                header('Location: ' . $returnTo);
            }
            if (PHP_SAPI !== 'cli') {
                exit;
            }
        }
    }

    /** @internal expose for advanced use */
    public function discovery(): Discovery
    {
        return $this->discovery;
    }

    /** @internal expose for advanced use */
    public function jwtVerifier(): JwtVerifier
    {
        return $this->jwtVerifier;
    }

    /**
     * รับเฉพาะ relative path ที่ปลอดภัย — กัน open redirect + header injection (F1).
     *
     * คืน null ถ้า:
     *   - มี CR/LF (header injection)
     *   - เป็น absolute URL: "http://", "//evil.com", "https:..." (open redirect)
     *   - มี backslash (browser บางตัวตีความเป็น /)
     * path ที่ผ่านต้องขึ้นต้นด้วย "/" หรือเป็น relative ภายในแอป
     */
    private static function sanitizeReturnPath(?string $path): ?string
    {
        if ($path === null || $path === '') {
            return null;
        }
        if (preg_match('/[\r\n\t]/', $path)) {
            return null; // CRLF / tab → header injection
        }
        if (str_contains($path, '\\')) {
            return null; // backslash → บาง browser ตีเป็น //
        }
        // absolute / protocol-relative URL → open redirect
        if (preg_match('#^[a-z][a-z0-9+.-]*:#i', $path) || str_starts_with($path, '//')) {
            return null;
        }
        return $path;
    }

    private function ensureSession(): void
    {
        if (PHP_SAPI === 'cli') {
            // ใน CLI ไม่มี session — caller ต้อง set $_SESSION เอง
            if (!isset($_SESSION)) {
                $GLOBALS['_SESSION'] = [];
            }
            return;
        }
        if (session_status() === PHP_SESSION_NONE) {
            session_start();
        }
    }
}
