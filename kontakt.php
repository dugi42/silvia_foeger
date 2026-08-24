<?php
/**
 * Nimmt das Kontaktformular entgegen und leitet die Nachricht per Mail weiter.
 *
 * Antwortet mit JSON, wenn das Formular per fetch() kommt, und mit einem
 * Redirect zurueck auf die Seite, wenn JavaScript aus ist.
 *
 * Bewusst ohne PHP-8-Syntax, damit es auch auf aelteren Shared Hosts laeuft.
 */

$redirectTarget = '/index.html#kontakt';

$recipient = trim((string) @include __DIR__ . '/mail-to.inc');

/** Beantwortet die Anfrage passend zum Absender und beendet das Skript. */
function respond($ok, $message, $status, $redirectTarget)
{
    $accept = isset($_SERVER['HTTP_ACCEPT']) ? $_SERVER['HTTP_ACCEPT'] : '';
    $wantsJson = strpos($accept, 'application/json') !== false;

    http_response_code($status);
    if ($wantsJson) {
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode(array('ok' => $ok, 'message' => $message), JSON_UNESCAPED_UNICODE);
        exit;
    }

    header('Location: ' . $redirectTarget . ($ok ? '?gesendet=1' : '?fehler=1'));
    exit;
}

$method = isset($_SERVER['REQUEST_METHOD']) ? $_SERVER['REQUEST_METHOD'] : '';
if ($method !== 'POST') {
    respond(false, 'Nur POST.', 405, $redirectTarget);
}

if ($recipient === '') {
    // Secret fehlt: lieber ehrlich scheitern als still verschlucken.
    respond(false, 'Der Versand ist gerade nicht eingerichtet.', 500, $redirectTarget);
}

// Honeypot: ein echtes Formular laesst dieses Feld leer, Bots fuellen es aus.
$trap = isset($_POST['website']) ? trim($_POST['website']) : '';
if ($trap !== '') {
    respond(true, 'Danke, ich melde mich!', 200, $redirectTarget);
}

$name = isset($_POST['name']) ? trim($_POST['name']) : '';
$email = isset($_POST['email']) ? trim($_POST['email']) : '';
$text = isset($_POST['nachricht']) ? trim($_POST['nachricht']) : '';

if ($name === '' || $text === '' || !filter_var($email, FILTER_VALIDATE_EMAIL)) {
    respond(false, 'Bitte Name, E-Mail und Nachricht ausfuellen.', 422, $redirectTarget);
}

$len = function_exists('mb_strlen') ? 'mb_strlen' : 'strlen';
if ($len($name) > 120 || $len($email) > 190 || $len($text) > 5000) {
    respond(false, 'Die Nachricht ist zu lang.', 422, $redirectTarget);
}

// Header-Injection ueber Zeilenumbrueche in Name oder Adresse verhindern.
$safeName = preg_replace('/[\r\n]+/', ' ', $name);
$safeEmail = preg_replace('/[\r\n]+/', '', $email);

$subject = 'Nachricht ueber silvia-foeger.at';
$body = 'Name: ' . $safeName . "\n"
    . 'E-Mail: ' . $safeEmail . "\n"
    . 'Gesendet: ' . date('d.m.Y H:i') . "\n\n"
    . $text . "\n";

$headers = array(
    'MIME-Version: 1.0',
    'Content-Type: text/plain; charset=utf-8',
    // Absender bleibt die eigene Domain, sonst greift SPF.
    'From: Website <' . $recipient . '>',
    'Reply-To: ' . $safeName . ' <' . $safeEmail . '>',
);

$sent = @mail(
    $recipient,
    '=?UTF-8?B?' . base64_encode($subject) . '?=',
    $body,
    implode("\r\n", $headers)
);

if (!$sent) {
    respond(false, 'Die Nachricht konnte nicht zugestellt werden.', 502, $redirectTarget);
}

respond(true, 'Danke, ich melde mich!', 200, $redirectTarget);
