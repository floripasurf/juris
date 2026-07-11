#!/usr/bin/env sh
# Go-live turnkey — prepara o Causia no Mac Mini (host always-on do piloto).
#
# Roda ON THE MAC MINI. Idempotente: pode rodar de novo sem estragar nada.
# Automatiza a parte determinística e segura (clone/sync/dirs/segredos/tenant/
# launchd da web) e IMPRIME os passos que precisam de decisão humana (tunnel,
# agente A3, cutover). Não usa sudo; nada é destrutivo sem confirmação.
#
#   sh scripts/golive_mac_mini.sh            # setup completo
#   REPO=git@github.com:floripasurf/juris.git BRANCH=feat/mni-mtls-token \
#     sh scripts/golive_mac_mini.sh
set -eu

PILOT_ROOT="${JURIS_PILOT_ROOT:-"$HOME/juris-pilot"}"
APP_DIR="${JURIS_APP_DIR:-"$PILOT_ROOT/app"}"
LOGS_DIR="$PILOT_ROOT/logs"
HOME_DIR="$PILOT_ROOT/home"
TENANTS_FILE="$PILOT_ROOT/tenants.json"
HMAC_FILE="$PILOT_ROOT/.hmac_key"
REPO="${REPO:-}"
BRANCH="${BRANCH:-feat/mni-mtls-token}"
PLIST="$HOME/Library/LaunchAgents/com.juris.web.plist"
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"

say() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
ok()  { printf '  \033[32mok\033[0m %s\n' "$1"; }
todo(){ printf '  \033[33m→\033[0m %s\n' "$1"; }

# ── 1. Código ────────────────────────────────────────────────────────────
say "1. Código em $APP_DIR"
mkdir -p "$PILOT_ROOT"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
  git -C "$APP_DIR" checkout --quiet "$BRANCH"
  git -C "$APP_DIR" reset --hard --quiet "origin/$BRANCH"
  ok "atualizado para origin/$BRANCH"
elif [ -n "$REPO" ]; then
  git clone --quiet --branch "$BRANCH" "$REPO" "$APP_DIR"
  ok "clonado de $REPO"
else
  echo "ERRO: $APP_DIR não existe e REPO não foi informado." >&2
  echo "  Rode: REPO=<git-url> sh scripts/golive_mac_mini.sh" >&2
  exit 1
fi
( cd "$APP_DIR" && "$UV" sync --frozen >/dev/null ) && ok "uv sync --frozen"

# ── 2. Diretórios e permissões (dados sensíveis: owner-only) ─────────────
say "2. Diretórios (owner-only)"
mkdir -p "$HOME_DIR/out" "$LOGS_DIR"
chmod 700 "$PILOT_ROOT" "$HOME_DIR" "$LOGS_DIR"
ok "$HOME_DIR e $LOGS_DIR com chmod 700"

# ── 3. Segredos ──────────────────────────────────────────────────────────
say "3. Segredos"
if [ ! -f "$HMAC_FILE" ]; then
  python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > "$HMAC_FILE"
  chmod 600 "$HMAC_FILE"
  ok "âncora HMAC do audit gerada ($HMAC_FILE)"
else
  ok "âncora HMAC já existe"
fi

# ── 4. Tenant do escritório piloto ───────────────────────────────────────
say "4. Tenant do piloto"
if [ ! -f "$TENANTS_FILE" ]; then
  todo "tenants.json não existe. Gere a chave e ENTREGUE-A ao advogado (aparece uma vez):"
  todo "  cd $APP_DIR && $UV run juris tenant new escritorio-piloto"
  todo "  # cole a linha hashada em $TENANTS_FILE  (formato: {\"escritorio-piloto\": \"sha256:...\"})"
  todo "  chmod 600 $TENANTS_FILE"
else
  chmod 600 "$TENANTS_FILE"
  ok "tenants.json presente (chmod 600)"
fi

# ── 5. Serviço web (launchd) ─────────────────────────────────────────────
say "5. Serviço web (launchd, porta 8000, loopback)"
HMAC_VALUE="$(cat "$HMAC_FILE")"
AGENTS_LINE=""
if [ -f "$PILOT_ROOT/agents.json" ]; then
  AGENTS_LINE="    <key>JURIS_AGENT_MODE</key><string>remote</string>
    <key>JURIS_AGENTS_FILE</key><string>$PILOT_ROOT/agents.json</string>"
fi
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.juris.web</string>
  <key>ProgramArguments</key>
  <array><string>$APP_DIR/.venv/bin/juris</string><string>web</string>
    <string>--host</string><string>127.0.0.1</string><string>--port</string><string>8000</string></array>
  <key>WorkingDirectory</key><string>$APP_DIR</string>
  <key>EnvironmentVariables</key><dict>
    <key>ENVIRONMENT</key><string>prod</string>
    <key>JURIS_REQUIRE_TENANTS</key><string>1</string>
    <key>JURIS_LOG_LEVEL</key><string>INFO</string>
    <key>JURIS_TENANTS_FILE</key><string>$TENANTS_FILE</string>
    <key>JURIS_HOME</key><string>$HOME_DIR</string>
    <key>JURIS_OUT_ROOT</key><string>$HOME_DIR/out</string>
    <key>JURIS_AUDIT_HMAC_KEY</key><string>$HMAC_VALUE</string>
$AGENTS_LINE
  </dict>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOGS_DIR/web.log</string>
  <key>StandardErrorPath</key><string>$LOGS_DIR/web.err</string>
</dict></plist>
PLISTEOF
ok "plist escrito em $PLIST"
if [ -f "$TENANTS_FILE" ]; then
  launchctl bootout "gui/$(id -u)/com.juris.web" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST" && ok "serviço (re)carregado"
  sleep 4
  code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/ || echo 000)"
  [ "$code" = "200" ] && ok "web responde 200 em 127.0.0.1:8000" || todo "web não respondeu ($code) — ver $LOGS_DIR/web.err"
else
  todo "pule este passo até criar o tenants.json (passo 4), depois rode o script de novo."
fi

# ── 6. Passos com decisão humana (tunnel, agente A3, cutover) ─────────────
say "6. Falta você fazer (máquina/token) — detalhes em docs/deploy/blackcube-pilot.md"
todo "TUNNEL: copie do MacBook para ESTE Mac Mini:"
todo "    ~/.cloudflared/cert.pem, ~/.cloudflared/<TUNNEL_ID>.json e ~/.cloudflared/config.yml"
todo "    depois: sudo cloudflared service install && cloudflared tunnel info juris"
todo "    e PARE o cloudflared no MacBook (cutover)."
todo "AGENTE A3 (co-localizado): plugue o token, e:"
todo "    cp $APP_DIR/docs/deploy/com.juris.agent.plist ~/Library/LaunchAgents/"
todo "    # edite JURIS_AGENT_TOKEN/CPF/SENHA/PIN + caminho PKCS#11; depois bootstrap"
todo "    # gere $PILOT_ROOT/agents.json {\"escritorio-piloto\":{\"url\":\"ws://127.0.0.1:8765\",\"token\":\"<token>\"}} e rode este script de novo"
todo "VALIDAR: cd $APP_DIR && $UV run juris doctor"

say "Pronto. Reexecute este script após criar tenants.json / agents.json."
