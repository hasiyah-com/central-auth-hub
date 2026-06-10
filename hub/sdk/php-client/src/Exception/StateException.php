<?php

declare(strict_types=1);

namespace CentralAuthHub\Exception;

/**
 * CSRF state mismatch — possible attack or expired session.
 * อ้างอิง RFC 6749 §10.12.
 */
class StateException extends HubException {}
