# Design — Native Messaging bridge to the browser LLM session

**Date:** 2026-06-25 · **Status:** juris-side done (protocol + transport); extension + host = next · **Implements:** ADR-0018

The lawyer's frontier model is their own Claude.ai/ChatGPT subscription, driven by
a Chrome extension on their machine. juris reaches it over the **Native Messaging**
chain — the same sanctioned mechanism the official Claude-for-Chrome uses with
Claude Code — so the AI session is a **local capability** in the ADR-0015 split
(it never leaves the lawyer's perimeter; the cloud orchestrator only sends a
de-identified prompt and receives a completion).

## Components

```
Cloud orchestrator
   │  (de-identified prompt — PIIMode.BROWSER_DEID)
   ▼
juris local agent  (api/local_agent.py, WS localhost)   ── BridgeChannel
   ▲↕  Native Messaging (stdio JSON)
Native Messaging Host  (small local executable, registered manifest)
   ▲↕  chrome.runtime messaging
Chrome extension  (content script)
   ▲↕  DOM
Claude.ai / ChatGPT tab  (lawyer logged in, training disabled)
```

| Piece | Status | Responsibility |
|---|---|---|
| `CompletionRequest` / `CompletionResponse` (`api/ws_schemas.py`) | ✅ done, tracked | The wire contract |
| `NativeBridgeTransport` (`api/browser_bridge.py`) | ✅ done, tracked | Serialise request → `BridgeChannel.request` → unwrap reply; satisfies `BrowserTransport` |
| `BrowserSessionLLM` (`llm/browser_session.py`) | ✅ done (local) | `AbstractLLM` over the transport |
| `WebSocketBridgeChannel` (`api/browser_bridge.py`) | ✅ done, tracked | WS client to the host: open → send JSON → await reply → close; injectable `connect` |
| Native Messaging Host | ⏳ next (OS glue) | Registered manifest; localhost WS server ↔ stdio to the extension |
| Chrome extension content script | ⏳ next (OS glue) | Inject prompt into the tab, extract the (streamed) reply |

The **entire juris (Python) side is built and tested**:
`BrowserSessionLLM → NativeBridgeTransport → WebSocketBridgeChannel → (host WS)`.
What remains is OS/Chrome-level: the native host (a small WS server that Chrome
launches and that relays to the extension over stdio) and the content script.

## Protocol

Request (juris → session):
```json
{ "request_id": "<uuid>", "prompt": "<de-identified>", "system": "<optional>",
  "model": "claude.ai (browser session)" }
```
Response (session → juris):
```json
{ "request_id": "<uuid>", "success": true, "content": "<reply>", "error": null }
```

`request_id` correlates concurrent calls. On UI failure (not logged in, layout
change, timeout) the extension returns `success: false` + `error`; the caller
falls back to the local model.

## Notes / open points for the extension build

- **Response extraction:** Claude.ai/ChatGPT stream tokens into a React DOM; the
  content script must detect completion (stop button → copy affordance) before
  reading, not race the stream.
- **Selector fragility:** isolate all DOM selectors in one module; degrade to
  `success:false` rather than returning a partial answer.
- **No structured-output guarantee:** the chat UI won't enforce JSON schemas — the
  prompt carries the format (the strategy/draft agents already do this).
- **Onboarding:** the lawyer must install the extension + host, log in, and
  **disable training/data collection** (Claude.ai Privacy / ChatGPT Data Controls)
  — a pilot checklist item (ADR-0018).
- **ToS:** lower risk for the firm's own use; revisit before multi-tenant resale.
