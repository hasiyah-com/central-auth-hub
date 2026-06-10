<?php
// ตัวอย่าง config — ใส่ค่าจริงของ subsystem ที่ลงทะเบียนกับ Hub
return [
    'hub_url'       => 'http://localhost:8000',
    'client_id'     => 'cli_xxxxxxxxxxxxxxxx',
    'client_secret' => 'sec_xxxxxxxxxxxxxxxx',  // pragma: allowlist secret
    'redirect_uri'  => 'http://localhost/subsystem/callback.php',
    'scope'         => ['openid', 'profile', 'email'],
];
