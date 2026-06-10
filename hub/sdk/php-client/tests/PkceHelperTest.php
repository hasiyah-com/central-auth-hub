<?php

declare(strict_types=1);

namespace CentralAuthHub\Tests;

use CentralAuthHub\PkceHelper;
use PHPUnit\Framework\TestCase;

final class PkceHelperTest extends TestCase
{
    public function testVerifierLengthInValidRange(): void
    {
        $v = PkceHelper::generateVerifier(64);
        $this->assertGreaterThanOrEqual(43, strlen($v));
        $this->assertLessThanOrEqual(128, strlen($v));
    }

    public function testVerifierUsesBase64Url(): void
    {
        $v = PkceHelper::generateVerifier(64);
        $this->assertMatchesRegularExpression('/^[A-Za-z0-9_-]+$/', $v);
    }

    public function testTwoVerifiersAreDifferent(): void
    {
        $a = PkceHelper::generateVerifier(64);
        $b = PkceHelper::generateVerifier(64);
        $this->assertNotSame($a, $b);
    }

    public function testRejectsTooShortLength(): void
    {
        $this->expectException(\InvalidArgumentException::class);
        PkceHelper::generateVerifier(32);
    }

    public function testRejectsTooLongLength(): void
    {
        $this->expectException(\InvalidArgumentException::class);
        PkceHelper::generateVerifier(200);
    }

    public function testChallengeIsBase64UrlSha256OfVerifier(): void
    {
        $verifier = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'; // pragma: allowlist secret
        $challenge = PkceHelper::challengeFor($verifier);
        $this->assertSame(
            'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM', // pragma: allowlist secret
            $challenge,
            'Must match RFC 7636 example'
        );
    }

    public function testChallengeIsDeterministic(): void
    {
        $verifier = 'abc123';
        $this->assertSame(
            PkceHelper::challengeFor($verifier),
            PkceHelper::challengeFor($verifier)
        );
    }
}
