<?php
// Manual test — SDK hardening (F1 return_path, F3 cache dir)
// รัน: E:\xampp\php\php.exe <thisfile>
require __DIR__ . '/../vendor/autoload.php';

use CentralAuthHub\Config;

$pass = 0;
$total = 0;
function chk(string $name, bool $cond): void
{
    global $pass, $total;
    $total++;
    if ($cond) {
        $pass++;
        echo "  [PASS] $name\n";
    } else {
        echo "  [FAIL] $name\n";
    }
}

// ── F1: sanitizeReturnPath (private) — เรียกผ่าน reflection ──
$ref = new ReflectionMethod('CentralAuthHub\Client', 'sanitizeReturnPath');
$ref->setAccessible(true);
$san = fn($v) => $ref->invoke(null, $v);

echo "── F1: return_path validation (กัน open redirect) ──\n";
chk('relative path ผ่าน', $san('profile.php') === 'profile.php');
chk('/dashboard ผ่าน', $san('/dashboard') === '/dashboard');
chk('absolute http → null', $san('http://evil.com') === null);
chk('https → null', $san('https://evil.com/x') === null);
chk('protocol-relative //evil → null', $san('//evil.com') === null);
chk('CRLF (header injection) → null', $san("ok\r\nSet-Cookie: x=1") === null);
chk('backslash → null', $san('\\\\evil.com') === null);
chk('null → null', $san(null) === null);
chk('empty → null', $san('') === null);
chk('javascript: scheme → null', $san('javascript:alert(1)') === null);

// ── F3: cacheDir per-client private ──
echo "\n── F3: cache dir (กัน shared /tmp poisoning) ──\n";
$cfg = new Config([
    'hub_url' => 'http://localhost:8000',
    'client_id' => 'cli_testF3',
    'client_secret' => 'sec_x',  // pragma: allowlist secret
    'redirect_uri' => 'http://localhost/cb',
]);
$dir = $cfg->cacheDir();
chk('cacheDir มี client_id hash (per-client)', str_contains($dir, substr(sha1('cli_testF3'), 0, 12)));
chk('cacheDir ถูกสร้างจริง', is_dir($dir));

$cfg2 = new Config([
    'hub_url' => 'http://localhost:8000',
    'client_id' => 'cli_otherF3',
    'client_secret' => 'sec_y',  // pragma: allowlist secret
    'redirect_uri' => 'http://localhost/cb',
]);
chk('คนละ client → คนละ cache dir (ไม่ชนกัน)', $cfg->cacheDir() !== $cfg2->cacheDir());

$cfg3 = new Config([
    'hub_url' => 'http://localhost:8000',
    'client_id' => 'cli_x',
    'client_secret' => 'sec_z',  // pragma: allowlist secret
    'redirect_uri' => 'http://localhost/cb',
    'cache_dir' => sys_get_temp_dir() . '/cah_custom_test',
]);
chk('cache_dir override ทำงาน', str_contains($cfg3->cacheDir(), 'cah_custom_test'));

// cleanup
@rmdir($dir);
@rmdir($cfg2->cacheDir());
@rmdir(sys_get_temp_dir() . '/cah_custom_test');

echo "\nRESULT: $pass/$total passed\n";
exit($pass === $total ? 0 : 1);
