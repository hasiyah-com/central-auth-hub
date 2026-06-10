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
    }
}
