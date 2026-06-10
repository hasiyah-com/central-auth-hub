<?php

declare(strict_types=1);

namespace CentralAuthHub\Tests;

use CentralAuthHub\Config;
use CentralAuthHub\Exception\HubException;
use PHPUnit\Framework\TestCase;

final class ConfigTest extends TestCase
{
    public function testValidConfigBuilds(): void
    {
        $c = new Config([
            'hub_url'       => 'http://localhost:8000',
            'client_id'     => 'cli_x',
            'client_secret' => 'sec_x', // pragma: allowlist secret
            'redirect_uri'  => 'http://localhost/cb',
        ]);
        $this->assertSame('http://localhost:8000', $c->hubUrl);
        $this->assertSame('cli_x', $c->clientId);
        $this->assertSame(['openid', 'profile', 'email'], $c->scope);
        $this->assertSame(600, $c->jwksCacheTtl);
        $this->assertSame('cah', $c->sessionKey);
    }

    public function testTrailingSlashStripped(): void
    {
        $c = new Config([
            'hub_url'       => 'http://localhost:8000/',
            'client_id'     => 'x',
            'client_secret' => 'y', // pragma: allowlist secret
            'redirect_uri'  => 'z',
        ]);
        $this->assertSame('http://localhost:8000', $c->hubUrl);
    }

    public function testMissingRequiredKeyThrows(): void
    {
        $this->expectException(HubException::class);
        $this->expectExceptionMessageMatches('/missing required key/');
        new Config([
            'client_id'     => 'x',
            'client_secret' => 'y', // pragma: allowlist secret
            'redirect_uri'  => 'z',
        ]);
    }

    public function testCustomScopeUsed(): void
    {
        $c = new Config([
            'hub_url'       => 'http://x',
            'client_id'     => 'x',
            'client_secret' => 'y', // pragma: allowlist secret
            'redirect_uri'  => 'z',
            'scope'         => ['email', 'student_id'],
        ]);
        $this->assertSame(['email', 'student_id'], $c->scope);
    }
}
