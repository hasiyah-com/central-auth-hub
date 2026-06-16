<?php

declare(strict_types=1);

namespace CentralAuthHub;

use CentralAuthHub\Exception\HubException;

/**
 * Fetch + cache `/.well-known/openid-configuration` (OIDC Discovery 1.0).
 *
 * Cache strategy: file-based ใน sys_get_temp_dir() — TTL configurable
 */
final class Discovery
{
    private Config $config;
    private ?array $cached = null;

    public function __construct(Config $config)
    {
        $this->config = $config;
    }

    /** @return array<string,mixed> the discovery document */
    public function get(): array
    {
        if ($this->cached !== null) {
            return $this->cached;
        }
        // try file cache
        $file = $this->cacheFile();
        if (is_file($file) && (time() - filemtime($file)) < $this->config->jwksCacheTtl) {
            $contents = @file_get_contents($file);
            if ($contents !== false) {
                $decoded = json_decode($contents, true);
                if (is_array($decoded)) {
                    return $this->cached = $decoded;
                }
            }
        }
        // fetch
        $url = $this->config->hubUrl . '/.well-known/openid-configuration';
        $ch  = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT        => $this->config->httpTimeout,
            CURLOPT_HTTPHEADER     => ['Accept: application/json'],
            // บังคับ verify TLS — กัน MITM (ช่องนี้ trust เป็น root ของ JWKS/issuer)
            CURLOPT_SSL_VERIFYPEER => true,
            CURLOPT_SSL_VERIFYHOST => 2,
        ]);
        $body = curl_exec($ch);
        $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $err  = curl_error($ch);
        curl_close($ch);

        if ($body === false || $code !== 200) {
            throw new HubException("Discovery fetch failed (HTTP $code): $err");
        }
        $decoded = json_decode($body, true);
        if (!is_array($decoded)) {
            throw new HubException('Discovery returned non-JSON');
        }
        // write cache (best-effort) — perms 0600 กัน co-tenant อ่าน/เขียนทับ (F3)
        @file_put_contents($file, $body, LOCK_EX);
        @chmod($file, 0600);
        return $this->cached = $decoded;
    }

    private function cacheFile(): string
    {
        $hash = substr(sha1($this->config->hubUrl), 0, 16);
        return $this->config->cacheDir() . "/discovery_{$hash}.json";
    }
}
