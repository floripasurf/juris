# Browser extension — the OS glue for the browser session (ADR-0018)

**Status:** scaffolding. The juris (Python) side is done and tested — protocol
(`api/ws_schemas.CompletionRequest/Response`), transport (`api/browser_bridge`),
and the Native Messaging **host framing** (`api/native_host`, unit-tested). What
remains needs **Chrome + Node** to build/test: the manifest, the content script
(DOM automation of the chat UI), and registering the native host.

## Chain (recap)

```
Cloud → juris local agent (WS) → native host (api/native_host) ⇄ extension (content.js) → Claude.ai/ChatGPT tab
                                   ✅ Python framing done            ⏳ JS (this dir)
```

## 1. `manifest.json` (Chrome MV3)

```json
{
  "manifest_version": 3,
  "name": "Juris — sessão de IA",
  "version": "0.1.0",
  "permissions": ["nativeMessaging", "scripting", "activeTab"],
  "host_permissions": ["https://claude.ai/*", "https://chatgpt.com/*"],
  "background": { "service_worker": "background.js" },
  "content_scripts": [
    { "matches": ["https://claude.ai/*", "https://chatgpt.com/*"], "js": ["content.js"] }
  ]
}
```

## 2. `content.js` (outline)

Receives a `CompletionRequest` (relayed from the native host via the background
service worker), drives the chat UI, returns a `CompletionResponse`.

```js
// All DOM selectors isolated here — they break on UI changes; degrade to
// { success: false, error } rather than returning a partial answer.
async function complete({ request_id, prompt, system }) {
  const box = document.querySelector('div[contenteditable="true"]'); // composer
  if (!box) return { request_id, success: false, error: "composer não encontrado" };
  box.focus();
  document.execCommand("insertText", false, (system ? system + "\n\n" : "") + prompt);
  // submit (Enter) and wait for the streamed reply to finish (stop button → copy)
  // ... extract the final assistant message text ...
  return { request_id, success: true, content: replyText };
}
```

## 3. Native host registration

`api/native_host.serve(handler)` is the host loop (framing done + tested).
Register it with Chrome via a host manifest, e.g. `com.juris.host.json`:

```json
{
  "name": "com.juris.host",
  "path": "/usr/local/bin/juris-native-host",
  "type": "stdio",
  "allowed_origins": ["chrome-extension://<EXTENSION_ID>/"]
}
```

The `handler` relays each `CompletionRequest` to the juris local agent over the
localhost WS (`api/browser_bridge.WebSocketBridgeChannel`) and returns the
`CompletionResponse`.

## Notes

- Onboarding (disable training, log in) is in `docs/pilot/onboarding.md §3.5`.
- De-id still applies upstream (the prompt arrives already de-identified).
- ToS caveat for multi-tenant resale: see ADR-0018.
