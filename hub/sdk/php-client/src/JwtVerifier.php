<?php

declare(strict_types=1);

namespace CentralAuthHub;

use CentralAuthHub\Exception\JwtException;
use Firebase\JWT\JWK;
use Firebase\JWT\JWT;

/**
 * JWT verification via JWKS (RFC 7517 + RFC 7519).
 *
 * - Cache JWKS file-based (TTL configurable)
 * - Refresh เมื่อเจอ kid ที่ไม่อยู่ใน cache (key rotation handling)
 * - Verify: signature + aud + iss + exp
 */
final class JwtVerifier
{
    private Config $config;
    private Discovery $discovery;

    public function __construct(Config $config, Discovery $discovery)
    {
        $this->config    = $config;
        $this->discovery = $discovery;
    }

    /**
     * @return array<string,mixed> verified claims
     * @throws JwtException
     */
    public function verify(string $accessToken): array
    {
        $disc = $this->discovery->get();
        $jwksUri = $disc['jwks_uri'] ?? null;
        $issuer  = $disc['issuer']   ?? null;
        if (!$jwksUri || !$issuer) {
            throw new JwtException('Discovery missing jwks_uri or issuer');
        }

        // Optional leeway สำหรับ clock skew
        JWT::$leeway = 30;

        try {
            $jwks = $this->loadJwks($jwksUri, refresh: false);
            $keys = JWK::parseKeySet($jwks);

            try {
                $decoded = JWT::decode($accessToken, $keys);
            } catch (\Throwable $e) {
                // อาจเป็น kid ใหม่จาก key rotation → ลอง refresh JWKS ทันที 1 ครั้ง
                $jwks = $this->loadJwks($jwksUri, refresh: true);
                $keys = JWK::parseKeySet($jwks);
                $decoded = JWT::decode($accessToken, $keys);
            }
        } catch (\Throwable $e) {
            throw new JwtException('JWT verify failed: ' . $e->getMessage(), 0, $e);
        }

        $claims = (array) $decoded;

        // Verify aud == our client_id
        $aud = $claims['aud'] ?? null;
        if ($aud !== $this->config->clientId) {
            throw new JwtException(
                "Audience mismatch — token aud=$aud, expected={$this->config->clientId}"
            );
        }

        // Verify iss == discovery issuer
        $iss = $claims['iss'] ?? null;
        if ($iss !== $issuer) {
            throw new JwtException("Issuer mismatch — token iss=$iss, expected=$issuer");
        }

        // exp verified by JWT::decode (with leeway)

        return $claims;
    }

    /** @return array<string,mixed> */
    private function loadJwks(string $jwksUri, bool $refresh): array
    {
        $cacheFile = $this->jwksCacheFile($jwksUri);
        if (!$refresh
            && is_file($cacheFile)
            && (time() - filemtime($cacheFile)) < $this->config->jwksCacheTtl
        ) {
            $contents = @file_get_contents($cacheFile);
            if ($contents !== false) {
                $decoded = json_decode($contents, true);
                if (is_array($decoded)) {
                    return $decoded;
                }
            }
        }

        $ch = curl_init($jwksUri);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT        => $this->config->httpTimeout,
        ]);
        $body = curl_exec($ch);
        $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $err  = curl_error($ch);
        curl_close($ch);

        if ($body === false || $code !== 200) {
            throw new JwtException("JWKS fetch failed (HTTP $code): $err");
        }
        $decoded = json_decode($body, true);
        if (!is_array($decoded) || !isset($decoded['keys'])) {
            throw new JwtException('JWKS returned invalid JSON');
        }
        @file_put_contents($cacheFile, $body, LOCK_EX);
        return $decoded;
    }

    private function jwksCacheFile(string $jwksUri): string
    {
        $hash = substr(sha1($jwksUri), 0, 16);
        return sys_get_temp_dir() . "/cah_jwks_{$hash}.json";
    }
}
