<?php

declare(strict_types=1);

namespace CentralAuthHub\Tests;

use CentralAuthHub\Client;
use CentralAuthHub\Discovery;
use CentralAuthHub\JwtVerifier;
use CentralAuthHub\Exception\JwtException;
use CentralAuthHub\Config;
use CentralAuthHub\WebhookReceiver;
use CentralAuthHub\Exception\HubException;
use PHPUnit\Framework\TestCase;

/**
 * End-to-end integration tests — ต้อง Hub backend ทำงานที่ http://localhost:8000
 *
 * Token จริงสร้างผ่าน Hub (server-side helper /test/issue-token)
 * หรือผ่าน env var TEST_HUB_TOKEN ที่ inject จาก script ภายนอก
 */
final class IntegrationTest extends TestCase
{
    private const HUB = 'http://localhost:8000';
    private const CLIENT_ID = 'cli_1ded036e86ec4c1b';

    protected function setUp(): void
    {
        // ปิด session warning ใน CLI
        if (!isset($_SESSION)) {
            $GLOBALS['_SESSION'] = [];
        }
    }

    public function testDiscoveryLoadable(): void
    {
        $cfg = new Config([
            'hub_url'       => self::HUB,
            'client_id'     => self::CLIENT_ID,
            'client_secret' => 'dummy', // pragma: allowlist secret
            'redirect_uri'  => 'http://localhost/cb',
        ]);
        $disc = (new Discovery($cfg))->get();
        $this->assertSame('https://hub.local', $disc['issuer']);
        $this->assertStringEndsWith('/.well-known/jwks.json', $disc['jwks_uri']);
        $this->assertContains('openid', $disc['scopes_supported']);
        $this->assertContains('profile', $disc['scopes_supported']);
        $this->assertContains('email', $disc['scopes_supported']);
        $this->assertSame(['code'], $disc['response_types_supported']);
        $this->assertContains('RS256', $disc['id_token_signing_alg_values_supported']);
    }

    public function testJwtVerifierAcceptsRealToken(): void
    {
        $token = $this->getRealToken();
        $cfg = new Config([
            'hub_url'       => self::HUB,
            'client_id'     => self::CLIENT_ID,
            'client_secret' => 'dummy', // pragma: allowlist secret
            'redirect_uri'  => 'http://localhost/cb',
        ]);
        $disc = new Discovery($cfg);
        $jv = new JwtVerifier($cfg, $disc);
        $claims = $jv->verify($token);

        $this->assertSame(self::CLIENT_ID, $claims['aud']);
        $this->assertSame('https://hub.local', $claims['iss']);
        $this->assertArrayHasKey('sub', $claims);
        $this->assertArrayHasKey('email', $claims);
        $this->assertArrayHasKey('exp', $claims);
        $this->assertArrayHasKey('jti', $claims);
    }

    public function testJwtVerifierRejectsTamperedSignature(): void
    {
        $token = $this->getRealToken();
        $parts = explode('.', $token);
        $tampered = $parts[0] . '.' . $parts[1] . '.AAAAAA';

        $cfg = new Config([
            'hub_url'       => self::HUB,
            'client_id'     => self::CLIENT_ID,
            'client_secret' => 'dummy', // pragma: allowlist secret
            'redirect_uri'  => 'http://localhost/cb',
        ]);
        $jv = new JwtVerifier($cfg, new Discovery($cfg));

        $this->expectException(JwtException::class);
        $jv->verify($tampered);
    }

    public function testJwtVerifierRejectsWrongAudience(): void
    {
        $token = $this->getRealToken();
        // token issued for cli_1ded... — verify ที่ aud=cli_other ต้องล้มเหลว
        $cfg = new Config([
            'hub_url'       => self::HUB,
            'client_id'     => 'cli_other_subsystem',
            'client_secret' => 'dummy', // pragma: allowlist secret
            'redirect_uri'  => 'http://localhost/cb',
        ]);
        $jv = new JwtVerifier($cfg, new Discovery($cfg));

        $this->expectException(JwtException::class);
        $this->expectExceptionMessageMatches('/(audience|aud).*mismatch/i');
        $jv->verify($token);
    }

    public function testClientStartLoginUrl(): void
    {
        $hub = new Client([
            'hub_url'       => self::HUB,
            'client_id'     => self::CLIENT_ID,
            'client_secret' => 'dummy', // pragma: allowlist secret
            'redirect_uri'  => 'http://localhost/cb',
        ]);
        $url = $hub->startLogin(returnPath: '/dashboard.php', sendRedirect: false);

        $this->assertStringContainsString('/oauth/authorize', $url);
        $this->assertStringContainsString('response_type=code', $url);
        $this->assertStringContainsString('code_challenge_method=S256', $url);
        $this->assertStringContainsString('client_id=' . self::CLIENT_ID, $url);
        $this->assertStringContainsString('scope=openid+profile+email', $url);
        $this->assertStringContainsString('state=', $url);
        $this->assertStringContainsString('code_challenge=', $url);

        // session ถูกเก็บ state + verifier
        $this->assertArrayHasKey('state', $_SESSION['cah']);
        $this->assertArrayHasKey('code_verifier', $_SESSION['cah']);
        $this->assertSame('/dashboard.php', $_SESSION['cah']['return_path']);
    }

    public function testWebhookReceiverAcceptsValidSignature(): void
    {
        $body = json_encode(['event' => 'access_revoked', 'hub_user_id' => 'u1']);
        $ts = (string) time();
        $key = 'shared-test-key';
        $sig = hash_hmac('sha256', $body, $key);
        $headers = [
            'x-hub-signature-256' => $sig,
            'x-hub-timestamp'     => $ts,
        ];

        $payload = WebhookReceiver::verify($key, 300, $body, $headers);
        $this->assertSame('access_revoked', $payload['event']);
        $this->assertSame('u1', $payload['hub_user_id']);
    }

    public function testWebhookReceiverRejectsBadSignature(): void
    {
        $body = json_encode(['x' => 1]);
        $ts = (string) time();
        $headers = [
            'x-hub-signature-256' => str_repeat('a', 64),  // wrong
            'x-hub-timestamp'     => $ts,
        ];
        $this->expectException(HubException::class);
        $this->expectExceptionMessageMatches('/signature mismatch/i');
        WebhookReceiver::verify('key', 300, $body, $headers);
    }

    public function testWebhookReceiverRejectsExpiredTimestamp(): void
    {
        $body = json_encode(['x' => 1]);
        $ts = (string) (time() - 600);  // 10 นาทีก่อน
        $key = 'k';
        $sig = hash_hmac('sha256', $body, $key);
        $headers = [
            'x-hub-signature-256' => $sig,
            'x-hub-timestamp'     => $ts,
        ];
        $this->expectException(HubException::class);
        $this->expectExceptionMessageMatches('/out of tolerance/i');
        WebhookReceiver::verify($key, 300, $body, $headers);
    }

    /**
     * Get a real JWT via Hub backend's internal helper.
     * Uses docker exec to run Python in container.
     */
    private function getRealToken(): string
    {
        $env = getenv('TEST_HUB_TOKEN');
        if ($env) {
            return $env;
        }
        $cmd = 'docker exec hub-backend python -c '
            . escapeshellarg('
from app.database import SessionLocal
from app.models import User, Subsystem, AccessList
from app.services.jwt_service import create_subsystem_token
db = SessionLocal()
user = db.query(User).filter(User.email.like("%@uni.ac.th")).first()
sub = db.query(Subsystem).filter(Subsystem.client_id == "cli_1ded036e86ec4c1b").first()
al = db.query(AccessList).filter(AccessList.subsystem_id == sub.id, AccessList.revoked_at.is_(None)).first()
token, _ = create_subsystem_token(user, sub.client_id, ["openid", "profile", "email"], al.role_in_sub if al else "user")
print(token, end="")
db.close()
            ');
        $token = trim((string) shell_exec($cmd));
        if ($token === '' || substr_count($token, '.') !== 2) {
            $this->markTestSkipped('cannot obtain real token from Hub (docker not available?)');
        }
        return $token;
    }
}
