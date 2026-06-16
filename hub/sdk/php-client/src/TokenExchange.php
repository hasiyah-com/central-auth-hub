<?php

declare(strict_types=1);

namespace CentralAuthHub;

use CentralAuthHub\Exception\TokenException;

/**
 * Exchange authorization code → access token via POST /oauth/token.
 */
final class TokenExchange
{
    private Config $config;
    private Discovery $discovery;

    public function __construct(Config $config, Discovery $discovery)
    {
        $this->config    = $config;
        $this->discovery = $discovery;
    }

    /**
     * @return array{access_token: string, token_type?: string, expires_in?: int, scope?: string, ...}
     * @throws TokenException
     */
    public function exchange(string $code, string $codeVerifier): array
    {
        $disc = $this->discovery->get();
        $tokenEndpoint = $disc['token_endpoint'] ?? null;
        if (!$tokenEndpoint) {
            throw new TokenException('Discovery missing token_endpoint');
        }

        $payload = http_build_query([
            'grant_type'    => 'authorization_code',
            'code'          => $code,
            'client_id'     => $this->config->clientId,
            'client_secret' => $this->config->clientSecret,
            'redirect_uri'  => $this->config->redirectUri,
            'code_verifier' => $codeVerifier,
        ]);

        $ch = curl_init($tokenEndpoint);
        curl_setopt_array($ch, [
            CURLOPT_POST           => true,
            CURLOPT_POSTFIELDS     => $payload,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT        => $this->config->httpTimeout,
            CURLOPT_HTTPHEADER     => [
                'Content-Type: application/x-www-form-urlencoded',
                'Accept: application/json',
            ],
            // บังคับ verify TLS — ช่องนี้ส่ง client_secret ห้ามให้ MITM อ่าน
            CURLOPT_SSL_VERIFYPEER => true,
            CURLOPT_SSL_VERIFYHOST => 2,
        ]);
        $body = curl_exec($ch);
        $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $err  = curl_error($ch);
        curl_close($ch);

        if ($body === false) {
            throw new TokenException("Token endpoint unreachable: $err");
        }
        if ($code !== 200) {
            throw new TokenException("Token exchange failed (HTTP $code): " . substr($body, 0, 200));
        }
        $decoded = json_decode($body, true);
        if (!is_array($decoded) || empty($decoded['access_token'])) {
            throw new TokenException('Token response missing access_token');
        }
        return $decoded;
    }
}
