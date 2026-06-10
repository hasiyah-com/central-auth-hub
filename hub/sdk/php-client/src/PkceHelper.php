<?php

declare(strict_types=1);

namespace CentralAuthHub;

/**
 * PKCE — RFC 7636.
 *  - code_verifier: 43-128 chars (we use 64)
 *  - code_challenge: BASE64URL(SHA256(verifier))
 *  - method: S256
 */
final class PkceHelper
{
    public static function generateVerifier(int $length = 64): string
    {
        if ($length < 43 || $length > 128) {
            throw new \InvalidArgumentException('verifier length must be 43..128 (RFC 7636 §4.1)');
        }
        $bytes = random_bytes($length);
        return self::base64UrlEncode($bytes);
    }

    public static function challengeFor(string $verifier): string
    {
        return self::base64UrlEncode(hash('sha256', $verifier, true));
    }

    private static function base64UrlEncode(string $bin): string
    {
        return rtrim(strtr(base64_encode($bin), '+/', '-_'), '=');
    }
}
