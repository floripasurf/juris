#!/usr/bin/env sh
set -eu

PILOT_ROOT="${JURIS_PILOT_ROOT:-"$HOME/juris-pilot"}"
APP_DIR="${JURIS_APP_DIR:-"$PILOT_ROOT/app"}"

export JURIS_REQUIRE_TENANTS="${JURIS_REQUIRE_TENANTS:-1}"
export JURIS_TENANTS_FILE="${JURIS_TENANTS_FILE:-"$PILOT_ROOT/tenants.json"}"
export JURIS_HOME="${JURIS_HOME:-"$PILOT_ROOT/home"}"
export JURIS_OUT_ROOT="${JURIS_OUT_ROOT:-"$JURIS_HOME/out"}"

if [ -z "${JURIS_AUDIT_HMAC_KEY:-}" ] && [ -r "$PILOT_ROOT/.hmac_key" ]; then
  JURIS_AUDIT_HMAC_KEY="$(cat "$PILOT_ROOT/.hmac_key")"
  export JURIS_AUDIT_HMAC_KEY
fi

if [ -z "${JURIS_AGENT_MODE:-}" ] && [ -r "$PILOT_ROOT/agents.json" ]; then
  export JURIS_AGENT_MODE=remote
  export JURIS_AGENTS_FILE="${JURIS_AGENTS_FILE:-"$PILOT_ROOT/agents.json"}"
fi

cd "$APP_DIR"
exec uv run juris doctor "$@"
