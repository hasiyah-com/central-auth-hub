# Central Auth Hub — PHP Client SDK

Official PHP SDK for **Central Auth Hub** — เชื่อม subsystem PHP เข้ากับ Hub ด้วย **OAuth 2.0 + PKCE + JWT** ผ่าน OIDC Discovery

> **เป้าหมาย:** ลด boilerplate จาก ~165 บรรทัด → ~10 บรรทัดต่อ flow

---

## ✅ ฟีเจอร์

- **Auto-discovery** — โหลด endpoint ทั้งหมดผ่าน `/.well-known/openid-configuration` (OIDC Discovery 1.0)
- **PKCE S256** สร้างให้อัตโนมัติ (RFC 7636)
- **CSRF state** — ป้องกัน + verify ด้วย `hash_equals` (RFC 6749 §10.12)
- **Token exchange** — POST `/oauth/token` พร้อม error handling
- **JWT verification** — signature + audience + issuer + expiry (RFC 7519)
- **JWKS caching** — file-based TTL 10 นาที + auto-refresh เมื่อ key rotation
- **Webhook receiver** — HMAC-SHA256 + replay protection (timing-safe)
- **Session management** — เก็บ user ใน `$_SESSION` namespaced
- **Typed exceptions** — `StateException`, `TokenException`, `JwtException`, `HubException`

---

## 📦 Install

```bash
composer require central-auth-hub/php-client
```

หรือใช้แบบ local (สำหรับ dev):

```json
{
  "repositories": [
    { "type": "path", "url": "../sdk/php-client" }
  ],
  "require": {
    "central-auth-hub/php-client": "*"
  }
}
```

---

## 🚀 5-minute integration

ใช้แค่ 4 ไฟล์:

### `config.php`
```php
return [
    'hub_url'       => 'http://localhost:8000',
    'client_id'     => 'cli_xxx',
    'client_secret' => 'sec_xxx',  // pragma: allowlist secret
    'redirect_uri'  => 'http://localhost/subsystem/callback.php',
    'scope'         => ['openid', 'profile', 'email'],
];
```

### `index.php` — หน้าแรก
```php
require 'vendor/autoload.php';
use CentralAuthHub\Client;

$hub = new Client(require 'config.php');
if ($hub->isAuthenticated()) {
    header('Location: dashboard.php');
    exit;
}
echo '<a href="login.php">Login with Hub</a>';
```

### `login.php` — start flow
```php
require 'vendor/autoload.php';
(new CentralAuthHub\Client(require 'config.php'))->startLogin('/dashboard.php');
```

### `callback.php` — verify + session
```php
require 'vendor/autoload.php';
$hub = new CentralAuthHub\Client(require 'config.php');
try {
    $result = $hub->handleCallback();
    header('Location: ' . ($result['return_path'] ?? 'dashboard.php'));
    exit;
} catch (CentralAuthHub\Exception\HubException $e) {
    http_response_code(400);
    die($e->getMessage());
}
```

### `dashboard.php` — ใช้ user info
```php
require 'vendor/autoload.php';
$hub = new CentralAuthHub\Client(require 'config.php');
if (!$hub->isAuthenticated()) {
    header('Location: index.php');
    exit;
}
$user = $hub->user();
echo "Hello, " . htmlspecialchars($user['name'] ?? $user['email']);
```

**รวม: ~25 บรรทัด** ครอบ login → callback → dashboard ครบ (เทียบกับ ~165 บรรทัดแบบเดิม)

---

## 📡 Webhook receiver

```php
use CentralAuthHub\WebhookReceiver;

$payload = WebhookReceiver::verify(getenv('HUB_WEBHOOK_SHARED_KEY'));
// payload = ['event'=>'access_revoked', 'hub_user_id'=>'...', ...]
if ($payload['event'] === 'access_revoked') {
    // ลบ user session, mark DB, ...
}
```

---

## 🔐 Security model

| Concern | Defense |
|---|---|
| CSRF (state) | `hash_equals` constant-time compare |
| Authorization code interception | PKCE S256 (RFC 7636) |
| Token theft | `client_secret` ส่งเฉพาะ server-side |
| JWT tampering | RS256 signature verify ผ่าน JWKS |
| Token replay | `exp` check (JWT::$leeway = 30s) |
| Key rotation | JWKS auto-refresh เมื่อเจอ kid ใหม่ |
| Webhook spoofing | HMAC-SHA256 + timestamp tolerance |

---

## 📚 References

- [OpenID Connect Discovery 1.0](https://openid.net/specs/openid-connect-discovery-1_0.html)
- [OpenID Connect Core 1.0 §5.3 (UserInfo)](https://openid.net/specs/openid-connect-core-1_0.html#UserInfo)
- [RFC 6749 (OAuth 2.0)](https://datatracker.ietf.org/doc/html/rfc6749)
- [RFC 7636 (PKCE)](https://datatracker.ietf.org/doc/html/rfc7636)
- [RFC 7517 (JWK)](https://datatracker.ietf.org/doc/html/rfc7517)
- [RFC 7519 (JWT)](https://datatracker.ietf.org/doc/html/rfc7519)

## 📜 License

MIT
