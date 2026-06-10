<?php

declare(strict_types=1);

namespace CentralAuthHub\Exception;

/** JWT verification failed (signature/aud/iss/exp). */
class JwtException extends HubException {}
