<?php
// TUTORIAL DE COMO USAR EM VIDEO MP4 NA PASTA TUTORIAL OK? RODE NA SIGILOPAY E SEJA FELIZ USANDO O NOSSO GATEWAY DE PAGAMENTO.

declare(strict_types=1);
date_default_timezone_set('America/Recife');

/**
 * ⚠️ SEGURANÇA (IMPORTANTE):
 * Você colou PUBLIC_KEY e SECRET_KEY aqui. Troque essas chaves no painel e substitua no código.
 * (Se alguém pegar isso, consegue gerar/transacionar pelo teu gateway.)
 */

/* ======= DEBUG (MOSTRA RESPOSTA DA API NA TELA) =======
   Abra assim: /sua-pagina.php?debug=1
====================================================== */
$DEBUG = (isset($_GET['debug']) && $_GET['debug'] === '1');

/* ======= ENDPOINT AJAX DE CHECAGEM (RETORNA JSON) ======= */
if (isset($_GET['check']) && $_GET['check'] === '1') {
    header('Content-Type: application/json; charset=utf-8');

    $tid = $_GET['tid'] ?? '';
    $tid = preg_replace('/[^a-zA-Z0-9_\-]/', '', $tid ?? '');

    if ($tid === '') {
        echo json_encode(['paid' => false], JSON_UNESCAPED_UNICODE);
        exit;
    }

    $dir  = __DIR__ . '/pagamentos';
    $file = $dir . '/' . $tid . '.json';

    $paid = is_file($file);
    echo json_encode(['paid' => $paid], JSON_UNESCAPED_UNICODE);
    exit;
}

/* ========== CONFIG (EDITE AQUI) ========== */
$CONFIG = (object)[
    'API_BASE'   => 'https://app.sigilopay.com.br/api/v1',
    'PUBLIC_KEY' => 'SUA CHAVE PUBLICA AQUI',
    'SECRET_KEY' => 'SUA CHAVE SECRETA AQUI',
    'ENDPOINT'   => '/gateway/pix/receive',

    // URL do callback (webhook.php)
    'CALLBACK_URL' => 'https://www.SEUSITE.COM/webhook.php',

    'PIX_HOLDER_FALLBACK' => 'SUA EMPRESA INTERMEDIAÇÕES LTDA',
    'CHECKOUT_MODEL'      => 'MODELO OU VERSAO OU ALGO AQUI',

    'FB_PIXEL_ID'         => 'DIGITE AQUI SEU PIXEL DO FACE',

    'THANKYOU' => (object)[
        'enabled' => false,
        'url'     => 'https://seusite.com/obrigado',
        'delay'   => 5,
    ],
];
/* ========== FIM CONFIG ========== */

/* ======= ENDPOINT AJAX "JÁ PAGUEI" (FORÇA CHECAGEM NA SIGILOPAY) ======= */
if (isset($_GET['force_check']) && $_GET['force_check'] === '1') {
    header('Content-Type: application/json; charset=utf-8');

    $tid = $_GET['tid'] ?? '';
    $tid = preg_replace('/[^a-zA-Z0-9_\-]/', '', $tid ?? '');

    if ($tid === '') {
        echo json_encode(['ok' => false, 'error' => 'TID inválido'], JSON_UNESCAPED_UNICODE);
        exit;
    }

    $url = rtrim($CONFIG->API_BASE, '/') . '/gateway/transactions';

    $payload = [
        'transactionId' => $tid, // ou 'identifier' => $tid, se a API usar o identifier
    ];

    // ✅ CORRIGIDO: header tem que ser "Header: valor"
    $headers = [
        'Content-Type: application/json',
        'Accept: application/json',
        'x-public-key: ' . $CONFIG->PUBLIC_KEY,
        'x-secret-key: ' . $CONFIG->SECRET_KEY,
    ];

    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_POST           => true,
        CURLOPT_POSTFIELDS     => json_encode($payload, JSON_UNESCAPED_UNICODE),
        CURLOPT_HTTPHEADER     => $headers,
        CURLOPT_CONNECTTIMEOUT => 10,
        CURLOPT_TIMEOUT        => 30,
        CURLOPT_SSL_VERIFYPEER => true,
    ]);

    $resp     = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $curlErr  = curl_error($ch);
    curl_close($ch);

    if ($resp === false) {
        echo json_encode([
            'ok'    => false,
            'error' => 'Erro ao conectar à API de transações. ' . ($curlErr ? '(' . $curlErr . ')' : ''),
        ], JSON_UNESCAPED_UNICODE);
        exit;
    }

    $json = json_decode($resp, true);

    echo json_encode([
        'ok'         => ($httpCode >= 200 && $httpCode < 300),
        'statusCode' => $httpCode,
        'raw'        => $resp,   // ✅ MOSTRA RAW
        'response'   => $json,
    ], JSON_UNESCAPED_UNICODE);
    exit;
}

function e(string $s): string {
    return htmlspecialchars($s, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function generateIdentifier(): string {
    return 'cashin_' . date('YmdHis') . '_' . bin2hex(random_bytes(3));
}

/** Parse TLV EMV → [tag => valor] */
function parseEmvTags(string $emv): array {
    $len  = strlen($emv);
    $i    = 0;
    $tags = [];

    while ($i + 4 <= $len) {
        $tag = substr($emv, $i, 2);
        $i  += 2;

        $size = (int)substr($emv, $i, 2);
        $i   += 2;

        if ($size < 0 || $i + $size > $len) {
            break;
        }

        $value = substr($emv, $i, $size);
        $i    += $size;

        $tags[$tag] = $value;
    }

    return $tags;
}

/** Extrai titular (59) e “instituição” do EMV PIX */
function parsePixInfoFromEmv(string $emv): array {
    $info = [
        'holder'      => null,
        'institution' => null,
    ];

    if ($emv === '') return $info;

    $top = parseEmvTags($emv);

    if (!empty($top['59'])) {
        $info['holder'] = trim($top['59']);
    }

    $acc = $top['26'] ?? ($top['27'] ?? null);
    if ($acc) {
        $sub = parseEmvTags($acc);
        $url = $sub['25'] ?? ($sub['01'] ?? null);

        if (!empty($url)) {
            if (stripos($url, 'http://') !== 0 && stripos($url, 'https://') !== 0) {
                $url = 'https://' . $url;
            }
            $host = parse_url($url, PHP_URL_HOST);
            if ($host) {
                $labels      = explode('.', $host);
                $institution = $host;

                $tld    = end($labels);
                $second = prev($labels);

                if (
                    in_array($tld, ['br','ar','uk','jp','au'], true) &&
                    in_array($second, ['com','net','org','gov','edu','co'], true) &&
                    count($labels) >= 3
                ) {
                    $institution = $labels[count($labels) - 3];
                } elseif (count($labels) >= 2) {
                    $institution = $labels[count($labels) - 2];
                }

                $info['institution'] = $institution;
            }
        }
    }

    return $info;
}

/* ===== Lógica do PIX ===== */
$pixPayload         = null;
$qrImageSrc         = null;
$pixHolderName      = null;
$pixInstitutionName = null;
$errorMsg           = null;
$requestIdentifier  = null;
$transactionId      = null;
$amountDisplay      = null;
$amountValue        = null;

/* ===== DEBUG CAPTURE ===== */
$apiUrlCalled = null;
$apiHttpCode  = null;
$apiRaw       = null;
$apiPretty    = null;
$apiCurlErr   = null;

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $raw = $_POST['amount'] ?? '';

    $formName     = trim($_POST['client_name']     ?? '');
    $formEmail    = trim($_POST['client_email']    ?? '');
    $formPhone    = trim($_POST['client_phone']    ?? '');
    $formDocument = trim($_POST['client_document'] ?? '');

    $clean = preg_replace('/[^\d\.,]/', '', (string)$raw);
    $clean = str_replace(',', '.', $clean);

    if ($formName === '' || $formEmail === '' || $formPhone === '' || $formDocument === '') {
        $errorMsg = 'Preencha todos os dados do pagador.';
    } elseif ($clean === '' || !is_numeric($clean)) {
        $errorMsg = 'Informe um valor válido.';
    } else {
        $valor = (float)$clean;
        if ($valor <= 0) {
            $errorMsg = 'O valor deve ser maior que zero.';
        } else {
            $amount        = round($valor, 2);
            $amountValue   = $amount;
            $amountDisplay = number_format($amount, 2, ',', '.');

            $requestIdentifier = generateIdentifier();

            $payload = [
                'identifier' => $requestIdentifier,
                'amount'     => $amount,
                'client'     => [
                    'name'     => $formName,
                    'email'    => $formEmail,
                    'phone'    => $formPhone,
                    'document' => $formDocument,
                ],
            ];

            if (!empty($CONFIG->CALLBACK_URL)) {
                $payload['callbackUrl'] = $CONFIG->CALLBACK_URL;
            }

            $url = rtrim($CONFIG->API_BASE, '/') . $CONFIG->ENDPOINT;
            $apiUrlCalled = $url;

            $headers = [
                'Content-Type: application/json',
                'Accept: application/json',
                'x-public-key: ' . $CONFIG->PUBLIC_KEY,
                'x-secret-key: ' . $CONFIG->SECRET_KEY,
            ];

            $ch = curl_init($url);
            curl_setopt_array($ch, [
                CURLOPT_RETURNTRANSFER => true,
                CURLOPT_POST           => true,
                CURLOPT_POSTFIELDS     => json_encode($payload, JSON_UNESCAPED_UNICODE),
                CURLOPT_HTTPHEADER     => $headers,
                CURLOPT_CONNECTTIMEOUT => 10,
                CURLOPT_TIMEOUT        => 30,
                CURLOPT_SSL_VERIFYPEER => true,
            ]);

            $resp     = curl_exec($ch);
            $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
            $curlErr  = curl_error($ch);
            curl_close($ch);

            // ===== DEBUG SAVE =====
            $apiHttpCode = $httpCode ?: null;
            $apiCurlErr  = $curlErr ?: null;
            $apiRaw      = ($resp === false) ? null : (string)$resp;

            if ($resp === false) {
                $errorMsg = 'Erro ao conectar à API. ' . ($curlErr ? '(' . $curlErr . ')' : '');
            } else {
                $json = json_decode($resp, true);

                if ($DEBUG) {
                    if (is_array($json)) {
                        $apiPretty = json_encode($json, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);
                    } else {
                        $apiPretty = null;
                    }
                }

                if (json_last_error() !== JSON_ERROR_NONE) {
                    $errorMsg = 'Resposta inválida da API.';
                } elseif ($httpCode < 200 || $httpCode >= 300) {
                    $msgApi   = $json['message'] ?? $json['errorDescription'] ?? 'Erro na API.';
                    $errorMsg = $msgApi;
                } else {
                    if (!empty($json['transactionId'])) {
                        $transactionId = (string)$json['transactionId'];
                    }

                    $pixNode = null;
                    if (isset($json['pix']) && is_array($json['pix'])) {
                        $pixNode = $json['pix'];
                    } elseif (isset($json['order']['pix']) && is_array($json['order']['pix'])) {
                        $pixNode = $json['order']['pix'];
                    }

                    if (is_array($pixNode)) {
                        $pixPayload =
                            $pixNode['code'] ??
                            $pixNode['payload'] ??
                            $pixNode['emv'] ??
                            $pixNode['qrCode'] ??
                            $pixNode['qrcode'] ??
                            null;

                        if (!empty($pixNode['base64'])) {
                            $b64 = $pixNode['base64'];
                            $qrImageSrc = (strpos($b64, 'data:image') === 0) ? $b64 : ('data:image/png;base64,' . $b64);
                        } elseif (!empty($pixNode['image'])) {
                            $qrImageSrc = $pixNode['image'];
                        } elseif (!empty($pixNode['imageUrl'])) {
                            $qrImageSrc = $pixNode['imageUrl'];
                        } elseif (!empty($pixNode['qrCodeImageUrl'])) {
                            $qrImageSrc = $pixNode['qrCodeImageUrl'];
                        }
                    }

                    if (!$pixPayload) {
                        $errorMsg = 'Transação criada, mas sem chave PIX na resposta.';
                    } else {
                        if (!$qrImageSrc) {
                            $qrUrl = 'https://api.qrserver.com/v1/create-qr-code/?size=220x220&data=' . urlencode($pixPayload);
                            $qrBinary = @file_get_contents($qrUrl);
                            $qrImageSrc = ($qrBinary !== false)
                                ? ('data:image/png;base64,' . base64_encode($qrBinary))
                                : $qrUrl;
                        }

                        $info = parsePixInfoFromEmv($pixPayload);
                        if (!empty($info['holder']))      $pixHolderName      = $info['holder'];
                        if (!empty($info['institution'])) $pixInstitutionName = $info['institution'];

                        if (!$pixHolderName && !empty($CONFIG->PIX_HOLDER_FALLBACK)) {
                            $pixHolderName = $CONFIG->PIX_HOLDER_FALLBACK;
                        }
                    }
                }
            }
        }
    }
}

$hasPix     = $pixPayload !== null;
$fbPixelId  = $CONFIG->FB_PIXEL_ID ?? '';
$thankyou   = $CONFIG->THANKYOU ?? null;
$tyEnabled  = $thankyou && !empty($thankyou->enabled);
$tyUrl      = $thankyou && !empty($thankyou->url) ? (string)$thankyou->url : null;
$tyDelay    = $thankyou && isset($thankyou->delay) ? (int)$thankyou->delay : 0;
?>
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>PIX SigiloPay</title>

  <?php if (!empty($fbPixelId)): ?>
    <script>
      !function(f,b,e,v,n,t,s){
        if(f.fbq)return;
        n=f.fbq=function(){n.callMethod?
          n.callMethod.apply(n,arguments):n.queue.push(arguments)};
        if(!f._fbq)f._fbq=n;
        n.push=n;
        n.loaded=!0;
        n.version='2.0';
        n.queue=[];
        t=b.createElement(e);
        t.async=!0;
        t.src=v;
        s=b.getElementsByTagName(e)[0];
        s.parentNode.insertBefore(t,s);
      }(window, document, 'script', 'https://connect.facebook.net/en_US/fbevents.js');

      fbq('init', '<?= e($fbPixelId) ?>');
      fbq('track', 'PageView');
    </script>
    <noscript>
      <img height="1" width="1" style="display:none"
           src="https://www.facebook.com/tr?id=<?= e($fbPixelId) ?>&ev=PageView&noscript=1"/>
    </noscript>
  <?php endif; ?>

  <style>
    :root{
      --bg: #201d25;
      --card-bg: #201d25;
      --card-border: #2b2633;
      --text: #ffffff;
      --muted: #a1a1aa;
      --input-bg: #16131b;
      --input-border: #34303a;
      --accent: #22c55e;
      --accent-text: #052e16;
      --danger-bg: #3f151a;
      --danger-text: #fecaca;
      --button-secondary-bg: #16131b;
      --button-secondary-border: #34303a;

      --debug-bg: rgba(0,0,0,.25);
      --debug-border: rgba(255,255,255,.14);
    }
    body[data-theme="light"]{
      --bg: #ffffff;
      --card-bg: #f7f7f7;
      --card-border: #e4e4e7;
      --text: #201d25;
      --muted: #71717a;
      --input-bg: #ffffff;
      --input-border: #d4d4d8;
      --accent: #22c55e;
      --accent-text: #022c22;
      --danger-bg: #fee2e2;
      --danger-text: #7f1d1d;
      --button-secondary-bg: #ffffff;
      --button-secondary-border: #d4d4d8;

      --debug-bg: rgba(0,0,0,.05);
      --debug-border: rgba(0,0,0,.08);
    }

    *{box-sizing:border-box;}
    html,body{margin:0;padding:0;height:100%;}
    body{
      font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      background:var(--bg);
      color:var(--text);
    }

    .theme-toggle-floating{
      position:fixed;
      top:12px;
      right:12px;
      width:36px;
      height:36px;
      border-radius:999px;
      display:flex;
      align-items:center;
      justify-content:center;
      background:rgba(0,0,0,.35);
      border:1px solid rgba(255,255,255,.18);
      backdrop-filter:blur(10px);
      cursor:pointer;
      z-index:20;
      transition:background .2s ease, box-shadow .2s ease, transform .15s ease;
    }
    body[data-theme="light"] .theme-toggle-floating{
      background:rgba(255,255,255,.9);
      border-color:rgba(0,0,0,.08);
    }
    .theme-toggle-floating:hover{
      transform:translateY(-1px);
      box-shadow:0 6px 18px rgba(0,0,0,.28);
    }
    .theme-toggle-floating svg{width:18px;height:18px;display:block;}
    .icon-sun, .icon-moon{display:none;}
    body[data-theme="dark"] .icon-sun{display:block;}
    body[data-theme="light"] .icon-moon{display:block;}

    .app{
      min-height:100vh;
      display:flex;
      align-items:center;
      justify-content:center;
      padding:16px;
    }
    .card{
      background:var(--card-bg);
      border-radius:16px;
      padding:22px 18px 18px;
      width:100%;
      max-width:420px;
      border:1px solid var(--card-border);
      box-shadow:0 16px 40px rgba(0,0,0,.3);
      position:relative;
    }
    @media (min-width:768px){
      .card{padding:24px 22px 22px;max-width:460px;}
    }
    h1{font-size:18px;margin:0 0 14px;text-align:center;font-weight:600;}
    label{display:block;font-size:13px;margin-bottom:6px;}
    input[type="text"], input[type="email"]{
      width:100%;
      padding:10px 11px;
      border-radius:10px;
      border:1px solid var(--input-border);
      background:var(--input-bg);
      color:var(--text);
      font-size:16px;
    }
    input::placeholder{color:var(--muted);}
    button{
      width:100%;
      padding:10px;
      border-radius:10px;
      border:0;
      background:var(--accent);
      color:var(--accent-text);
      font-weight:600;
      font-size:14px;
      cursor:pointer;
      margin-top:10px;
      transition:opacity .15s ease;
    }
    button.secondary{
      background:var(--button-secondary-bg);
      color:var(--text);
      border:1px solid var(--button-secondary-border);
    }
    button:disabled{opacity:.6;cursor:not-allowed;}
    button:hover:not(:disabled){opacity:.95}

    .error{
      background:var(--danger-bg);
      color:var(--danger-text);
      border-radius:10px;
      padding:8px 10px;
      font-size:13px;
      margin-bottom:10px;
    }

    .pix-box{margin-top:6px}
    .pix-input{margin-top:6px}
    .pix-input input{font-size:13px}
    .small{font-size:11px;color:var(--muted);margin-top:8px;text-align:center;}
    .tx-id{font-size:11px;color:var(--muted);text-align:center;margin-top:8px;word-break:break-all;}
    .holder{font-size:11px;color:var(--muted);margin-top:6px;text-align:center;}
    .holder strong{font-weight:600;color:var(--text);}
    .qr-wrapper{display:flex;justify-content:center;margin:12px 0 8px;}
    .qr-frame{
      position:relative;
      padding:4px;
      border-radius:10px;
      background:transparent;
      border:1px dashed #34303a;
    }
    .qr-frame img{
      display:block;width:220px;height:220px;border-radius:6px;background:#ffffff;
    }
    .qr-download-btn{
      position:absolute;right:6px;bottom:6px;width:24px;height:24px;border-radius:999px;
      border:1px solid rgba(255,255,255,.4);background:rgba(0,0,0,.8);
      display:flex;align-items:center;justify-content:center;cursor:pointer;
      transition:opacity .12s ease, transform .12s ease;z-index:5;color:#e5e5e5;
    }
    .qr-download-btn:hover{opacity:.95;transform:translateY(-1px);}
    .qr-download-btn svg{width:13px;height:13px;display:block;}

    #paidStep{display:none;text-align:center;margin-top:4px;}
    .paid-icon-badge{
      width:58px;height:58px;border-radius:999px;margin:4px auto 10px;
      display:flex;align-items:center;justify-content:center;
      background:rgba(34,197,94,0.12);border:1px solid rgba(34,197,94,0.9);
    }
    .paid-icon-badge svg{width:28px;height:28px;color:#22c55e;display:block;}
    .paid-title{font-size:17px;font-weight:600;margin-bottom:4px;}
    .paid-sub{font-size:12px;color:var(--muted);margin-bottom:6px;}
    #btnJaPaguei{display:none;margin-top:8px;}

    /* DEBUG BOX */
    .debug{
      margin-top:14px;
      padding:10px;
      border-radius:12px;
      background:var(--debug-bg);
      border:1px solid var(--debug-border);
      overflow:hidden;
    }
    .debug h2{
      margin:0 0 8px;
      font-size:12px;
      font-weight:700;
      color:var(--muted);
      text-transform:uppercase;
      letter-spacing:.04em;
    }
    .debug .meta{
      font-size:11px;
      color:var(--muted);
      margin-bottom:8px;
      word-break:break-all;
    }
    .debug pre{
      margin:0;
      white-space:pre-wrap;
      word-break:break-word;
      font-size:11px;
      line-height:1.35;
      padding:10px;
      border-radius:10px;
      border:1px solid var(--debug-border);
      background:rgba(0,0,0,.25);
    }
    body[data-theme="light"] .debug pre{background:rgba(255,255,255,.75);}
  </style>
</head>
<body data-theme="dark">
  <div class="theme-toggle-floating" id="themeToggle" aria-label="Alternar tema" title="Alternar tema">
    <svg class="icon-sun" viewBox="0 0 24 24" fill="none">
      <path d="M12 4V2M12 22v-2M4.93 4.93L3.51 3.51M20.49 20.49l-1.42-1.42M4 12H2M22 12h-2M4.93 19.07L3.51 20.49M20.49 3.51l-1.42 1.42M12 8a4 4 0 100 8 4 4 0 000-8z"
        stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    <svg class="icon-moon" viewBox="0 0 24 24" fill="none">
      <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"
        stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
  </div>

  <div class="app">
    <div class="card">
      <?php if ($hasPix): ?>
        <div id="pixStep">
          <h1>PIX de R$ <?= $amountDisplay ? e($amountDisplay) : '' ?></h1>

          <div class="qr-wrapper">
            <div class="qr-frame">
              <?php if ($qrImageSrc): ?>
                <img id="qrImg" src="<?= e($qrImageSrc) ?>" alt="QR Code PIX">
              <?php endif; ?>
              <button type="button" class="qr-download-btn" onclick="downloadQr()" title="Baixar QR Code">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M12 3v12m0 0l-4-4m4 4l4-4M5 19h14"
                    fill="none" stroke="currentColor" stroke-width="1.8"
                    stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              </button>
            </div>
          </div>

          <?php if ($pixHolderName || $pixInstitutionName): ?>
            <div class="holder">
              <?php if ($pixHolderName): ?>
                Titular: <strong><?= e($pixHolderName) ?></strong>
              <?php endif; ?>
              <?php if ($pixInstitutionName): ?>
                <br><span style="font-size:10px;">Instituição: <?= e($pixInstitutionName) ?></span>
              <?php endif; ?>
            </div>
          <?php endif; ?>

          <?php if ($transactionId): ?>
            <div class="tx-id">
              Transação:<br><strong><?= e($transactionId) ?></strong>
            </div>
          <?php endif; ?>

          <div class="pix-box">
            <label for="pixKey">PIX copia e cola</label>
            <div class="pix-input">
              <input id="pixKey" type="text" readonly value="<?= e($pixPayload) ?>">
            </div>
            <button type="button" onclick="copyPix()">Copiar chave PIX</button>

            <button type="button" id="btnJaPaguei" class="secondary">
              Já paguei, verificar pagamento
            </button>

            <button type="button" class="secondary"
              onclick="window.location.href = window.location.pathname + <?= $DEBUG ? "'?debug=1'" : "''" ?>;">
              Gerar nova cobrança
            </button>
          </div>

          <?php if (!empty($CONFIG->CHECKOUT_MODEL)): ?>
            <div class="small"><?= e($CONFIG->CHECKOUT_MODEL) ?></div>
          <?php endif; ?>

          <?php if ($DEBUG): ?>
            <div class="debug">
              <h2>DEBUG — Resposta da API (pix/receive)</h2>
              <div class="meta">
                <div><strong>URL:</strong> <?= e((string)$apiUrlCalled) ?></div>
                <div><strong>HTTP:</strong> <?= $apiHttpCode !== null ? e((string)$apiHttpCode) : '—' ?></div>
                <?php if ($apiCurlErr): ?><div><strong>cURL:</strong> <?= e((string)$apiCurlErr) ?></div><?php endif; ?>
              </div>
              <pre><?= e($apiPretty ?? ($apiRaw ?? '—')) ?></pre>
            </div>
          <?php endif; ?>
        </div>

        <div id="paidStep">
          <div class="paid-icon-badge">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
              <path d="M20 7L9 18l-5-5" fill="none" stroke="currentColor"
                stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </div>
          <div class="paid-title">Pagamento aprovado</div>
          <div class="paid-sub">PIX de R$ <?= $amountDisplay ? e($amountDisplay) : '—' ?> confirmado.</div>

          <?php if ($transactionId): ?>
            <div class="tx-id">
              Transação:<br><strong><?= e($transactionId) ?></strong>
            </div>
          <?php endif; ?>

          <div class="small">Liberado o acesso/serviço ao cliente.</div>
          <div id="redirectMsg" class="small"></div>
        </div>

      <?php else: ?>
        <h1>Gerar PIX</h1>

        <?php if ($errorMsg): ?>
          <div class="error"><?= e($errorMsg) ?></div>
        <?php endif; ?>

        <form method="post" action="<?= e($_SERVER['PHP_SELF'] . ($DEBUG ? '?debug=1' : '')) ?>">
          <label for="client_name">Nome completo</label>
          <input id="client_name" name="client_name" type="text" placeholder="Ex: João da Silva" autocomplete="name" required />

          <label for="client_email">E-mail</label>
          <input id="client_email" name="client_email" type="email" placeholder="Ex: joao@gmail.com" autocomplete="email" required />

          <label for="client_phone">WhatsApp / Telefone</label>
          <input id="client_phone" name="client_phone" type="text" placeholder="Ex: (11) 99999-9999" autocomplete="tel" required />

          <label for="client_document">CPF/CNPJ</label>
          <input id="client_document" name="client_document" type="text" placeholder="Ex: 000.000.000-00" autocomplete="off" required />

          <label for="amount" style="margin-top:10px;">Valor (R$)</label>
          <input id="amount" name="amount" type="text" placeholder="Ex: 50,00" autocomplete="off" required />

          <button type="submit">Gerar cobrança PIX</button>
        </form>

        <div class="small">
          Página interna de cash-in SigiloPay.<br>
          Checkout com dados básicos do pagador (preenchimento obrigatório).
        </div>

        <?php if (!empty($CONFIG->CHECKOUT_MODEL)): ?>
          <div class="small"><?= e($CONFIG->CHECKOUT_MODEL) ?></div>
        <?php endif; ?>

        <?php if ($DEBUG && $_SERVER['REQUEST_METHOD'] === 'POST'): ?>
          <div class="debug">
            <h2>DEBUG — Resposta da API (pix/receive)</h2>
            <div class="meta">
              <div><strong>URL:</strong> <?= e((string)$apiUrlCalled) ?></div>
              <div><strong>HTTP:</strong> <?= $apiHttpCode !== null ? e((string)$apiHttpCode) : '—' ?></div>
              <?php if ($apiCurlErr): ?><div><strong>cURL:</strong> <?= e((string)$apiCurlErr) ?></div><?php endif; ?>
            </div>
            <pre><?= e($apiPretty ?? ($apiRaw ?? '—')) ?></pre>
          </div>
        <?php endif; ?>

      <?php endif; ?>
    </div>
  </div>

  <script>
    function copyPix(){
      const input = document.getElementById('pixKey');
      if(!input) return;
      input.select();
      input.setSelectionRange(0, 99999);
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(input.value).then(()=>{ alert('Chave PIX copiada'); });
      } else {
        document.execCommand('copy');
        alert('Chave PIX copiada');
      }
    }

    function downloadQr(){
      const img = document.getElementById('qrImg');
      if (!img || !img.src) return;
      const link = document.createElement('a');
      link.href = img.src;
      link.download = 'pix-qrcode.png';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }

    const amt = document.getElementById('amount');
    if (amt) {
      amt.addEventListener('input', e => {
        e.target.value = e.target.value.replace(/[^\d\.,]/g, '');
      });
    }

    const body   = document.body;
    const toggle = document.getElementById('themeToggle');

    (function initTheme(){
      const saved   = localStorage.getItem('sp_theme');
      const initial = (saved === 'light' || saved === 'dark') ? saved : 'dark';
      body.setAttribute('data-theme', initial);
    })();

    if (toggle) {
      toggle.addEventListener('click', () => {
        const current = body.getAttribute('data-theme') || 'dark';
        const next    = current === 'dark' ? 'light' : 'dark';
        body.setAttribute('data-theme', next);
        localStorage.setItem('sp_theme', next);
      });
    }

    const HAS_PIX        = <?php echo $hasPix && $transactionId ? 'true' : 'false'; ?>;
    const TID            = <?php echo $transactionId ? json_encode($transactionId, JSON_UNESCAPED_UNICODE) : 'null'; ?>;
    const AMOUNT_VALUE   = <?php echo $amountValue !== null ? json_encode($amountValue) : 'null'; ?>;
    const FB_ENABLED     = <?php echo !empty($fbPixelId) ? 'true' : 'false'; ?>;
    const THANKYOU_ENABLED = <?php echo $tyEnabled ? 'true' : 'false'; ?>;
    const THANKYOU_URL     = <?php echo $tyUrl ? json_encode($tyUrl) : 'null'; ?>;
    const THANKYOU_DELAY   = <?php echo $tyDelay; ?>;

    function markPaid(){
      const pixStep  = document.getElementById('pixStep');
      const paidStep = document.getElementById('paidStep');
      if (pixStep)  pixStep.style.display  = 'none';
      if (paidStep) paidStep.style.display = 'block';

      if (FB_ENABLED && typeof fbq === 'function' && AMOUNT_VALUE && !window.__FB_PURCHASE_SENT__) {
        const params = { value: AMOUNT_VALUE, currency: 'BRL' };
        if (TID) {
          params.contents    = [{ id: TID }];
          params.content_ids = [TID];
        }
        fbq('track', 'Purchase', params);
        window.__FB_PURCHASE_SENT__ = true;
      }

      if (THANKYOU_ENABLED && THANKYOU_URL) {
        const msg = document.getElementById('redirectMsg');
        if (msg && THANKYOU_DELAY > 0) {
          msg.textContent = 'Você será redirecionado em ' + THANKYOU_DELAY + ' segundos...';
        }
        const delayMs = (THANKYOU_DELAY > 0 ? THANKYOU_DELAY : 1) * 1000;
        setTimeout(() => { window.location.href = THANKYOU_URL; }, delayMs);
      }
    }

    // ===== Botão "Já paguei" ====
    (function setupJaPaguei(){
      if (!HAS_PIX || !TID) return;

      const btn = document.getElementById('btnJaPaguei');
      if (!btn) return;

      const INITIAL_DELAY_MS  = 20000;
      const COOLDOWN_DELAY_MS = 20000;

      setTimeout(() => { btn.style.display = 'block'; }, INITIAL_DELAY_MS);

      let cooling = false;

      btn.addEventListener('click', async () => {
        if (cooling) return;
        cooling = true;

        const originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = 'Verificando pagamento...';

        try {
          const url = window.location.pathname + '<?= $DEBUG ? "?debug=1&" : "?" ?>' + 'force_check=1&tid=' + encodeURIComponent(TID);
          await fetch(url, { method: 'GET', cache: 'no-store' });
          btn.textContent = 'Já paguei (aguarde alguns instantes)';
        } catch (e) {
          btn.textContent = 'Erro ao verificar, tente novamente';
        }

        setTimeout(() => {
          cooling = false;
          btn.disabled = false;
          btn.textContent = originalText;
        }, COOLDOWN_DELAY_MS);
      });
    })();

    (function startPaymentWatcher(){
      if (!HAS_PIX || !TID) return;

      if (FB_ENABLED && typeof fbq === 'function' && AMOUNT_VALUE) {
        fbq('track', 'InitiateCheckout', { value: AMOUNT_VALUE, currency: 'BRL' });
      }

      let timer = setInterval(async () => {
        try {
          const url = window.location.pathname + '<?= $DEBUG ? "?debug=1&" : "?" ?>' + 'check=1&tid=' + encodeURIComponent(TID);
          const res = await fetch(url, { cache: 'no-store' });
          if (!res.ok) return;
          const data = await res.json();
          if (data && data.paid) {
            clearInterval(timer);
            markPaid();
          }
        } catch(e){
          // silencioso
        }
      }, 5000);
    })();
  </script>
</body>
</html>
