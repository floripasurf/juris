# Deployment & scaling — reverse channel, rate limit, health

The pilot runs **single-worker** and co-located (Mac Mini). Everything below is about
what to change *before* scaling the cloud orchestrator to multiple workers/instances,
so remote MNI/filing and rate limiting keep working.

## The single-worker constraint (why)

Two pieces of state live **in process memory** today:

| State | Where | Consequence of multi-worker |
|---|---|---|
| Reverse-channel agent connections | `RelayHub` singleton by default; Redis broker when `JURIS_RELAY_BROKER` is set | Without sticky/broker, an agent registers on one worker and a request can land on another. |
| Rate-limit counters | `web/rate_limit.py` | Per-process counters → the effective limit is `N_workers × limit`. |

**Pilot rule:** run the orchestrator with **one worker** when the reverse channel or
rate limiting is in use (`uvicorn ... --workers 1`; no horizontal replicas). Health
`GET /api/health?deep=1` and the admin panel make a broken agent visible immediately.

**Fail-closed guard (enforced in code):** `RelayHub.send()` refuses to route under
multi-worker (`WEB_CONCURRENCY`/`JURIS_WEB_WORKERS > 1`) unless you explicitly opt into a
safe topology — either `JURIS_RELAY_BROKER=<url>` (Redis broker) or `JURIS_RELAY_STICKY=1`
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

## Scaling option B — Redis relay broker (real horizontal scale)

Status: **built in code; real Redis integration smoke automated and passing**
(`scripts/smoke_relay_broker.py`, 2026-07-05) — two `RelayHub` instances sharing
one real Redis prove cross-worker routing + `SET NX` dedupe. Repeat the smoke
against the target Redis/network before enabling production multi-worker remote mode.
Set:

```bash
JURIS_RELAY_BROKER=redis://redis:6379/0
```

How it works:

1. **Agent worker subscribes by tenant.** When `/ws/agent-relay?tenant=<id>` accepts the
   agent WebSocket, `RelayHub.register()` subscribes that worker to
   `juris:relay:request:<tenant>`.
2. **Any worker can send.** `RelayHub.send()` publishes the `AgentRequest` to that tenant
   request channel and waits on a hashed reply channel for the same `request_id`.
3. **Agent replies through the broker.** The worker holding the WebSocket receives the
   agent response and publishes it to the correlated reply channel.
4. **Duplicate request guard.** Redis `SET NX` protects `tenant/request_id` while the
   request is pending. Reads may be retried manually; **signing/filing must not be
   automatically retried** without an idempotency/reconciliation design.
5. **Presence.** The worker holding the agent socket writes a TTL heartbeat key so health
   checks can report a tenant agent connected even if the current HTTP request lands on a
   different worker.

Before enabling in production, run the real Redis integration smoke
(`scripts/smoke_relay_broker.py`) — it stands up two `RelayHub(broker=...)`
instances (worker A + worker B) sharing one Redis and asserts (1) an agent on A
answers a request entering B and (2) a concurrent duplicate `request_id` is
rejected by `SET NX`:

```bash
docker run -d --name smoke-redis -p 6399:6379 redis:7-alpine
JURIS_RELAY_BROKER=redis://127.0.0.1:6399/0 uv run python scripts/smoke_relay_broker.py
docker rm -f smoke-redis
```

Expected: `SMOKE BROKER OK` and exit 0. The WebSocket transport itself (agent
dialer ↔ `/ws/agent-relay`) is covered by `tests/unit/api/test_relay.py`; this
smoke covers the routing/dedupe layer that needs a real Redis + two workers. For
a full end-to-end proof against your target infra, additionally connect a real
agent to worker A and force an MNI read/dry-run filing through worker B.

## Rate limit for production

`web/rate_limit.py` is process-local by default (fine single-worker). For multi-worker,
pick one:

- **Redis (shared quota) — built in:** set `JURIS_RATE_LIMIT_REDIS_URL=redis://host:6379/0`.
  `build_rate_limiter` then uses `RedisFixedWindowRateLimiter` (atomic `INCR`+`EXPIRE` per
  tenant+window) so N workers enforce ONE global quota. Fails OPEN if Redis is unreachable
  (the API stays up; the proxy is the hard backstop). Tune with
  `JURIS_API_RATE_LIMIT_PER_MINUTE`.
- **Reverse proxy:** additionally/alternatively enforce at nginx (`limit_req_zone` by
  `$http_x_api_key`) or the gateway, treating the app limiter as a local safety net.

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
