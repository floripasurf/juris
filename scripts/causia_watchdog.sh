#!/bin/sh
# Watchdog do CAUSIA no Mac Mini: se a web local não responder HTTP em 10s por
# 2 execuções seguidas, faz kickstart do serviço launchd. KeepAlive religa
# processo MORTO; isto cobre processo PENDURADO (hang), que o KeepAlive não vê.
#
# Qualquer status HTTP conta como vivo — 401 sem chave é o esperado (fail-closed);
# o alvo é hang/morte da web, não autenticação. O tunnel/DNS caído NÃO é detectado
# aqui (é interno ao Mini) — para isso use o monitor externo (runbook §5).
set -u

PORT="${CAUSIA_WEB_PORT:-8100}"
LABEL="${CAUSIA_WEB_LABEL:-com.causia.web}"
STATE="${CAUSIA_WATCHDOG_STATE:-${TMPDIR:-/tmp}/causia_watchdog_failcount}"

http_code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' "http://127.0.0.1:${PORT}/api/health" || echo 000)

if [ "$http_code" != "000" ]; then
  rm -f "$STATE" 2>/dev/null || true
  exit 0
fi

fails=$(( $(cat "$STATE" 2>/dev/null || echo 0) + 1 ))
echo "$fails" > "$STATE"

if [ "$fails" -ge 2 ]; then
  echo "$(date '+%F %T') watchdog: web sem resposta (${fails}x) — kickstart ${LABEL}"
  launchctl kickstart -k "gui/$(id -u)/${LABEL}"
  echo 0 > "$STATE"
fi
