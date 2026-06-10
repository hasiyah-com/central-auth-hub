<?php

declare(strict_types=1);

namespace CentralAuthHub;

use CentralAuthHub\Exception\StateException;

/**
 * State management for CSRF protection (RFC 6749 §10.12).
 *
 * Stored in $_SESSION under namespace key — verify with hash_equals (timing-safe).
 */
final class StateHelper
{
    public static function generate(): string
    {
        return bin2hex(random_bytes(16));
    }

    /** @throws StateException on mismatch/missing */
    public static function verifyAndConsume(string $sessionKey, string $providedState): void
    {
        if (!isset($_SESSION[$sessionKey]['state'])) {
            throw new StateException('No state in session — session expired or never started');
        }
        $expected = (string) $_SESSION[$sessionKey]['state'];
        // consume immediately — กัน replay
        unset($_SESSION[$sessionKey]['state']);

        if (!hash_equals($expected, $providedState)) {
            throw new StateException('State mismatch — possible CSRF attack');
        }
    }
}
