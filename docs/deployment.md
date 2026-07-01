# Deployment & scaling — reverse channel, rate limit, health

The pilot runs **single-worker** and co-located (Mac Mini). Everything below is about
what to change *before* scaling the cloud orchestrator to multiple workers/instances,
so remote MNI/filing and rate limiting keep working.

## The single-worker constraint (why)

Two pieces of state live **in process memory** today:

| State | Where | Consequence of multi-worker |
|---|---|---|
| Reverse-channel agent connections | `RelayHub` singleton (`api/relay.py`) | An agent registers on the worker that terminated its WebSocket; `send()` only finds it there. A request landing on another worker fails to route. |
| Rate-limit counters | `web/rate_limit.py` | Per-process counters → the effective limit is `N_workers × limit`. |

**Pilot rule:** run the orchestrator with **one worker** when the reverse channel or
rate limiting is in use (`uvicorn ... --workers 1`; no horizontal replicas). Health
`GET /api/health?deep=1` and the admin panel make a broken agent visible immediately.

**Fail-closed guard (enforced in code):** `RelayHub.send()` refuses to route under
multi-worker (`WEB_CONCURRENCY`/`JURIS_WEB_WORKERS > 1`) unless you explicitly opt into a
safe topology — either `JURIS_RELAY_BROKER=<url>` (a real broker) or `JURIS_RELAY_STICKY=1`
(you assert LB affinity by tenant is configured). Plain multi-worker with neither **fails
loudly** — an MNI read / filing raises a clear error instead of silently landing on a
worker that isn't holding the agent's connection. Scaling therefore never *silently*
breaks MNI/filing; it either works (single worker / sticky / broker) or errors visibly.
Note `JURIS_RELAY_STICKY` is an *assertion*, not a verification — you own the LB affinity.

## Scaling option A — sticky sessions (smallest change)

Pin each firm's traffic (and its dialed-in agent WebSocket) to one worker/instance by
tenant, so the in-memory hub always has the connection.

- **Affinity key:** the tenant (API key / `x-api-key`, or the `?tenant=` on
  `/ws/agent-relay`). Hash it to a backend.
- **nginx:** `upstream juris { hash $http_x_api_key consistent; }` and a matching
  `hash` on the WS `location /ws/agent-relay` using `$arg_tenant`.
- **Traefik/Envoy:** consistent-hash LB on the same header/query.
- WebSockets must stick for the whole connection (they already do with hash-LB).
- **Then set `JURIS_RELAY_STICKY=1`** on the workers so the fail-closed guard
  (`reverse_channel_scaling_ok`) allows routing — without it, multi-worker `send()` refuses.

Good enough for a handful of firms. It does **not** survive a worker restart mid-session
(the agent reconnects and re-registers — see
`test_two_tenants_survive_agent_reconnect`, which proves the hub re-routes correctly to
the new socket and the stale one can't hijack).

## Scaling option B — external broker (real horizontal scale)

Replace the in-memory maps with a broker so any worker can reach any agent:

1. **Relay:** Redis pub/sub or NATS keyed by tenant. The worker holding the agent
   socket subscribes to `agent:<tenant>`; `send()` publishes the `AgentRequest` there
   and awaits the correlated reply on `reply:<tenant>:<request_id>`. `RelayHub`'s
   interface (`register`/`unregister`/`send`/`resolve`) already isolates this — swap the
   `_agents`/`_pending` dicts for broker calls; the endpoint and `relay_token_ok` are
   unchanged.
2. **Idempotency:** reads are safe to retry; **signing/filing is not** — keep the
   `request_id` de-dupe (`request_id duplicado` guard) and never auto-retry a filing.

## Rate limit for production

`web/rate_limit.py` is process-local by design. For multi-worker:

- **Reverse proxy** (simplest): enforce at nginx (`limit_req_zone` by `$http_x_api_key`)
  or the API gateway, and treat the app limiter as a local safety net.
- **Redis** (shared quota): move the counter to Redis (`INCR` + `EXPIRE` per
  tenant+window) so the limit is global across workers.

## Operational health

- `GET /api/health?deep=1` — per-tenant readiness; **deep by default** so a
  required-but-unreachable agent/token shows `degraded`, not `ok`. `?deep=false` for a
  fast shallow check. Expensive probes are cached ~10s.
- `GET /api/admin/health` — every tenant at once; gated by `$JURIS_ADMIN_TOKEN` via the
  `x-admin-token` header (404 when unset, 401 on mismatch). Use it to spot a degraded
  firm before they call.

## Done-when checklist (Sprint 3)

- [x] Single-worker requirement documented (here + `api/relay.py` docstring).
- [x] Two-tenant agent-reconnect correctness under test (`test_two_tenants_survive_agent_reconnect`).
- [x] Fail-closed guard so multi-worker never *silently* breaks MNI/filing
      (`reverse_channel_scaling_ok`, `test_relay_send_fails_closed_under_multiworker`).
- [ ] Sticky sessions **or** broker wired in the actual deploy (infra — pick A or B above).
- [ ] Rate limit moved to proxy/Redis in the actual deploy (infra).
