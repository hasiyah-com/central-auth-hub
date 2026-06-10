<?php
require __DIR__ . '/../vendor/autoload.php';

use CentralAuthHub\Client;

$hub = new Client(require __DIR__ . '/config.php');
$hub->logout(sendRedirect: true, returnTo: 'index.php');
