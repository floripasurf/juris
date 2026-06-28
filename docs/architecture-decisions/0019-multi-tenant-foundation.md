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

**Done (this ADR):** the auth + storage-scoping primitives, tested, open by
default. Ready to wire as a dependency on the API without breaking Phase 1.

**Next (Phase 2 activation):**
1. Add `Depends(current_tenant)` to the API and thread the `Tenant` through.
2. Scope every store by `tenant_scoped_dir` — the LocalDB, the repertory, the
   `juris-out` output root, the audit log — so no tenant reads another's data.
3. Per ADR-0015, swap the InProcess services for `Remote*` clients talking to each
   firm's local agent (the token never co-locates with the cloud orchestrator).
4. Rate limiting + a durable audit sink (the sibling SaaS uses Redis + Cloud
   Logging) for production operation.

**Risk:** API keys in a JSON file suit the pilot; a real deployment needs hashed
keys + rotation + a secrets store. Flagged for Phase 2.
