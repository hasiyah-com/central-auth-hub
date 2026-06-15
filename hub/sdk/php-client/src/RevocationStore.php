<?php

declare(strict_types=1);

namespace CentralAuthHub;

/**
 * File-based revocation store — สำหรับ PHP subsystem ที่ไม่มี DB.
 *
 * เก็บ "user X (หรือทั้งระบบ) ถูก revoke/update เมื่อ timestamp T" ลงไฟล์ JSON
 * แล้ว Client.isAuthenticated() เช็คว่า session ปัจจุบันเก่ากว่า T ไหม → ถ้าใช่
 * = ต้อง re-auth (เด้งไป login เหมือนหอพัก hub_access_revoked_at).
 *
 * รูปแบบไฟล์:
 *   { "users": { "<hub_user_id>": <epoch_ts>, ... }, "all": <epoch_ts> }
 *   - users[id] = เวลา revoke/update ของ user คนนั้น (role change)
 *   - all       = เวลา config เปลี่ยน (kick ทุกคน)
 *
 * ใช้ flock กัน race ตอนเขียนพร้อมกัน.
 */
final class RevocationStore
{
    private string $path;

    public function __construct(string $path)
    {
        $this->path = $path;
        $dir = dirname($path);
        if (!is_dir($dir)) {
            @mkdir($dir, 0775, true);
        }
    }

    /** @return array{users: array<string,int>, all: int} */
    private function read(): array
    {
        if (!is_file($this->path)) {
            return ['users' => [], 'all' => 0];
        }
        $raw = @file_get_contents($this->path);
        $data = $raw ? json_decode($raw, true) : null;
        if (!is_array($data)) {
            return ['users' => [], 'all' => 0];
        }
        return [
            'users' => is_array($data['users'] ?? null) ? $data['users'] : [],
            'all'   => (int) ($data['all'] ?? 0),
        ];
    }

    private function write(array $data): void
    {
        $fp = @fopen($this->path, 'c+');
        if ($fp === false) {
            return; // fail-safe — ไม่ทำให้ webhook ล่ม
        }
        try {
            flock($fp, LOCK_EX);
            ftruncate($fp, 0);
            rewind($fp);
            fwrite($fp, json_encode($data, JSON_UNESCAPED_SLASHES));
            fflush($fp);
        } finally {
            flock($fp, LOCK_UN);
            fclose($fp);
        }
    }

    /** mark user คนหนึ่งต้อง re-auth (role change) — ts default = now */
    public function markUser(string $hubUserId, ?int $ts = null): void
    {
        $ts = $ts ?? time();
        $data = $this->read();
        $cur = (int) ($data['users'][$hubUserId] ?? 0);
        $data['users'][$hubUserId] = max($cur, $ts);
        $this->write($data);
    }

    /** mark ทุกคนต้อง re-auth (config/scope เปลี่ยน) — ts default = now */
    public function markAll(?int $ts = null): void
    {
        $ts = $ts ?? time();
        $data = $this->read();
        $data['all'] = max((int) $data['all'], $ts);
        $this->write($data);
    }

    /**
     * True ถ้า user คนนี้ถูก revoke/update **หลัง** เวลา $loggedInAt
     * (ครอบทั้ง per-user และ all) → caller บังคับ re-login.
     */
    public function isRevokedSince(string $hubUserId, int $loggedInAt): bool
    {
        $data = $this->read();
        $userTs = (int) ($data['users'][$hubUserId] ?? 0);
        $allTs  = (int) $data['all'];
        return ($userTs > $loggedInAt) || ($allTs > $loggedInAt);
    }
}
