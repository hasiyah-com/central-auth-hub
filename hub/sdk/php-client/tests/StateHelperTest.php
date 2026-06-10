<?php

declare(strict_types=1);

namespace CentralAuthHub\Tests;

use CentralAuthHub\Exception\StateException;
use CentralAuthHub\StateHelper;
use PHPUnit\Framework\TestCase;

final class StateHelperTest extends TestCase
{
    protected function setUp(): void
    {
        // Fake $_SESSION
        $GLOBALS['_SESSION'] = [];
    }

    public function testGenerateIs32HexChars(): void
    {
        $s = StateHelper::generate();
        $this->assertSame(32, strlen($s));
        $this->assertMatchesRegularExpression('/^[0-9a-f]{32}$/', $s);
    }

    public function testValidStateConsumes(): void
    {
        $_SESSION['ns']['state'] = 'abc123';
        StateHelper::verifyAndConsume('ns', 'abc123');
        $this->assertArrayNotHasKey('state', $_SESSION['ns'], 'state must be consumed');
    }

    public function testStateMismatchThrows(): void
    {
        $_SESSION['ns']['state'] = 'expected';
        $this->expectException(StateException::class);
        StateHelper::verifyAndConsume('ns', 'attacker_value');
    }

    public function testMissingStateThrows(): void
    {
        $this->expectException(StateException::class);
        StateHelper::verifyAndConsume('ns', 'something');
    }

    public function testTimingSafeComparison(): void
    {
        // เราใช้ hash_equals — verify ว่า function ทำงานถูกต้อง
        $_SESSION['ns']['state'] = 'abcd1234';
        // เกือบเท่ากันแต่ตัวสุดท้ายต่าง
        $this->expectException(StateException::class);
        StateHelper::verifyAndConsume('ns', 'abcd1235');
    }
}
