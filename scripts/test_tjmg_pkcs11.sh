#!/bin/bash
# Test TJMG mTLS with PKCS#11 hardware token
# Usage: cd ~/juris && ./scripts/test_tjmg_pkcs11.sh

set -euo pipefail

OPENSSL="/opt/homebrew/opt/openssl@3/bin/openssl"
# brew upgrades move the versioned engines dir; point at the stable symlink
export OPENSSL_ENGINES="/opt/homebrew/lib/engines-3"
PKCS11_MODULE="/usr/local/lib/libeTPkcs11.dylib"
HOST="pje-consulta-publica.tjmg.jus.br"
PATH_URL="/pje/intercomunicacao"
CERT="/tmp/juris_user_cert.pem"
CHAIN="/tmp/juris_chain.pem"

# The key ID shared by cert, public key, and private key on the token
KEY_ID="%79%70%44%5A%2D%53%6B%39%42%54%79%42%53%51%56%42%49%51%55%56%4D%49%45%31%42%55%6C%52%4A"

echo "=== Checking prerequisites ==="
for f in "$OPENSSL" "$PKCS11_MODULE" "$CERT" "$CHAIN"; do
  [ -f "$f" ] && echo "  OK: $f" || { echo "  MISSING: $f"; exit 1; }
done

"$OPENSSL" engine pkcs11 2>&1 | grep -q "pkcs11" && echo "  OK: pkcs11 engine" || { echo "  ERROR: no pkcs11 engine"; exit 1; }

# Get PIN (never embed in URI or log it)
if [ -z "${TOKEN_PIN:-}" ]; then
  echo -n "Token PIN: "
  read -s TOKEN_PIN
  echo
fi

# Get the lawyer's PJe password for MNI application-level login
if [ -z "${MNI_SENHA:-}" ]; then
  echo -n "Senha do PJe TJMG (para o login MNI): "
  read -s MNI_SENHA
  echo
fi

export PKCS11_MODULE_PATH="$PKCS11_MODULE"

# Write an OpenSSL config that sets the PIN securely via the engine config
OPENSSL_CONF=$(mktemp)
cat > "$OPENSSL_CONF" << CONFEOF
openssl_conf = openssl_init

[openssl_init]
engines = engine_section

[engine_section]
pkcs11 = pkcs11_section

[pkcs11_section]
engine_id = pkcs11
MODULE_PATH = ${PKCS11_MODULE}
PIN = ${TOKEN_PIN}
init = 0
CONFEOF

# Private key URI — use the shared ID to find the private key (not the cert label)
KEY_URI="pkcs11:token=TOKEN%20CERTDATA;id=${KEY_ID};type=private"

# Build SOAP request
SOAP='<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns="http://www.cnj.jus.br/servico-intercomunicacao-2.2.3/">
  <soap:Body>
    <ns:consultarProcesso>
      <idConsultante>07671039632</idConsultante>
      <senhaConsultante>'"$MNI_SENHA"'</senhaConsultante>
      <numeroProcesso>5082351-40.2017.8.13.0024</numeroProcesso>
      <movimentos>true</movimentos>
      <incluirCabecalho>true</incluirCabecalho>
      <incluirDocumentos>false</incluirDocumentos>
    </ns:consultarProcesso>
  </soap:Body>
</soap:Envelope>'

CONTENT_LENGTH=${#SOAP}
REQFILE=$(mktemp)
printf "POST %s HTTP/1.1\r\nHost: %s\r\nContent-Type: text/xml; charset=utf-8\r\nContent-Length: %d\r\nSOAPAction: \"\"\r\nConnection: close\r\n\r\n%s" \
  "$PATH_URL" "$HOST" "$CONTENT_LENGTH" "$SOAP" > "$REQFILE"

echo ""
echo "=== Testing mTLS to $HOST ==="
echo "  Key URI: pkcs11:token=TOKEN CERTDATA;id=...;type=private"
echo ""

OPENSSL_CONF="$OPENSSL_CONF" "$OPENSSL" s_client \
  -engine pkcs11 \
  -keyform engine \
  -key "$KEY_URI" \
  -cert "$CERT" \
  -CAfile "$CHAIN" \
  -connect "${HOST}:443" \
  -servername "$HOST" \
  -quiet \
  < "$REQFILE" \
  > /tmp/juris_mtls_response.txt \
  2>/tmp/juris_mtls_stderr.txt

RC=$?

# Clean up temp files (contain PIN)
rm -f "$OPENSSL_CONF" "$REQFILE"

echo "=== openssl exit code: $RC ==="
echo ""

# Show stderr (filter out PIN if it leaked)
echo "=== Stderr ==="
sed 's/PIN = .*/PIN = ***/' /tmp/juris_mtls_stderr.txt
echo ""

echo "=== Response (first 2000 chars) ==="
head -c 2000 /tmp/juris_mtls_response.txt
echo ""
echo ""

if grep -q "sucesso.*true" /tmp/juris_mtls_response.txt 2>/dev/null; then
  echo "[SUCCESS] MNI returned sucesso=true!"
elif grep -q "sucesso.*false" /tmp/juris_mtls_response.txt 2>/dev/null; then
  echo "[AUTH FAILED] MNI returned sucesso=false"
  grep -o "mensagem>[^<]*<" /tmp/juris_mtls_response.txt 2>/dev/null || true
elif grep -q "HTTP" /tmp/juris_mtls_response.txt 2>/dev/null; then
  echo "[GOT HTTP RESPONSE]"
else
  echo "[ERROR] No valid response"
fi

echo ""
echo "Full response: /tmp/juris_mtls_response.txt ($(wc -c < /tmp/juris_mtls_response.txt) bytes)"

# Clean stderr file (may contain PIN)
rm -f /tmp/juris_mtls_stderr.txt
