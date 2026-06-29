# ADR-0019: Multi-tenant foundation — tenant auth + storage scoping

**Status:** Accepted (foundation) · **Date:** 2026-06-28 · **Relates to:** ADR-0015 (local agent), ADR-0016 (PII)

## Context

Phase 1 is "SaaS for one" — co-located on the firm's own Mac Mini, single user,
open. Phase 2 is multi-tenant: many firms, isolated data, and (per ADR-0015) a
Remote local-agent per firm holding the A3 token. The foundation must not disturb
the Phase-1 pilot.

## Decision

**Tenant identity by API key** (`X-API-Key`), the pattern proven by sibling legal
SaaS. Implemented in `web/auth.py`:

- `TenantRegistry` maps `{tenant_id: api_key}` (loaded from `$JURIS_TENANTS_FILE`,
  default `config/tenants.json`). **No tenants configured ⇒ open**: every request
  resolves to the shared `public` tenant, so Phase 1 is unchanged.
- `current_tenant` — a FastAPI dependency that resolves the request's `Tenant`
  (401 on a missing/invalid key when tenants are configured).
- `tenant_scoped_dir(tenant, base)` — per-account storage root: shared `base` for
  `public`, `base/tenants/<id>` otherwise.

## Consequences

**Done (activated):**
- `Depends(current_tenant)` on every API endpoint (processos, prazos, detail,
  connect, audit, demo-runs) — auth enforced (401 on a bad key) when configured,
  open ⇒ `public` otherwise (Phase 1 unchanged).
- Tenant-scoped storage: the read endpoints use a per-tenant `LocalDB`
  (`tenant_db_path`); demo runs write under the tenant's `juris-out`; the audit
  endpoint is confined to the tenant's output root (no cross-tenant reads).
- API keys: `hash_api_key` (sha256) + constant-time auth accepting **plaintext
  (dev) or hashed (production)** stored values. **Rotation** = update the tenants
  file and reload (`default_registry.cache_clear`).
- **Write path scoped**: `run_connect(db=...)` threads the tenant's `LocalDB`
  through the tracked list (`get/set_tracked(db=)`, now backed by a
  `tracked_processos` table) and the nightly sync (`run_nightly(db=)`) — import
  and sync write to the tenant's own store, not the global acervo.
- **Hardening**: connect jobs carry their `tenant_id` and `GET /api/connect/{id}`
  is 404 for non-owners; the demo/audit output root is **server-controlled**
  (`$JURIS_OUT_ROOT`, client `out_root` ignored); `tenant_id` is validated
  (`^[a-zA-Z0-9_-]+$`) before it becomes a path segment.
- **Fail-closed switch**: `JURIS_REQUIRE_TENANTS=1` makes an open registry (no
  tenants file) reject every request instead of falling back to `public` — set it
  in production so a missing config can't silently open the deployment.
- **Key format**: stored keys are `sha256:<hex>` (explicit prefix) or plaintext —
  no ambiguity between the two. `hash_api_key` emits the prefixed form.
- **Resource**: `_tenant_db` caches one `LocalDB` per storage path (engine/pool
  reused across requests), not one per request.

**Next (Phase 2):**
1. Per ADR-0015, swap the InProcess services for `Remote*` clients talking to each
   firm's local agent (the token never co-locates with the cloud orchestrator).
2. Move connect jobs out of the in-process dict into a per-tenant durable queue.
3. Rate limiting + a durable audit sink (Redis + Cloud Logging) + a secrets store
   for the keys file.
