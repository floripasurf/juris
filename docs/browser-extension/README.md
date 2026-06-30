# Browser extension — the OS glue for the browser session (ADR-0018)

Uses the **lawyer's own Claude.ai/ChatGPT subscription** to run completions, driven
by the juris local agent through a Native Messaging bridge. The juris (Python) side
is done and tested — protocol (`api/ws_schemas.CompletionRequest/Response`),
transport (`api/browser_bridge`), and the host framing (`api/native_host`). This
directory is the **MV3 extension** (the JS half).

## Chain

```
juris agent → native host (api/native_host) ⇄ background.js → content.js → Claude.ai/ChatGPT tab
```

## Files

| File | Role |
|---|---|
| `manifest.json` | MV3 manifest — minimal perms (`nativeMessaging`, `tabs`) + the two provider hosts |
| `selectors.js` | **Isolated per-provider DOM selectors + extraction** (the brittle part; unit-tested) |
| `content.js` | Completion flow: inject prompt → wait for generation to finish → extract → reply |
| `background.js` | Service worker: relays host ⇄ content script |
| `native-host.json` | Native-messaging host manifest (set the real extension id + host path) |
| `selectors.test.js` | vitest + jsdom unit tests for the selectors/parsers |

## Build, test

```bash
npm install
npm test          # vitest — selectors/parsers against a jsdom DOM fixture
npm run build     # esbuild bundles content.js (+ selectors) → dist/content.js
npm run package   # build + zip → dist/juris-extension.zip (distributable)
```

`dist/` and `node_modules/` are gitignored — run `npm run build` before loading.

## Load in Chrome (smoke test)

1. `npm run build`.
2. `chrome://extensions` → Developer mode → **Load unpacked** → this folder.
3. Copy the extension id and install the native host:
   ```bash
   uv run juris browser install-native-host --extension-id <EXTENSION_ID>
   export JURIS_BROWSER_BRIDGE_URL=ws://127.0.0.1:8787
   ```
   The command writes the per-user Chrome manifest (`com.juris.host`) and a local
   launcher under `~/.juris/browser-session/`.
4. Open Claude.ai (or ChatGPT) and **log in**; in onboarding, disable training/history.
5. Check readiness:
   ```bash
   uv run juris browser status
   ```
6. Drive a completion from the juris agent → it should appear in the tab and the
   final text return as a `CompletionResponse`.

## Robustness (built in)

- Selectors isolated per provider in `selectors.js` — retune in one place when a UI changes.
- 120s timeout; polls until the **stop/streaming** control disappears **and** the text
  is non-empty and stable — a partial/streaming answer is **never** returned as success.
- `detectBlocker()` catches a **login wall** or **usage/rate limit** (selector + text
  patterns) before and after sending → a precise error, never a silent empty answer.
- Send prefers the provider's **send button**, falling back to Enter; the prompt is
  inserted via `execCommand` + an `input` event so the React editor registers it.
- Clear errors: `provedor não suportado`, `sessão não logada — faça login`,
  `limite de uso atingido`, `nenhuma aba aberta`, `timeout aguardando a resposta`.

The operator console shows the active AI mode, de-id posture, and whether the
native host manifest is installed (`GET /api/ai-session`).

## Security

- The prompt arrives **already de-identified** (juris de-id runs before the bridge).
- Minimal `host_permissions` (only the two providers); no broad tab access.
- Prompts are **not persisted** in JS — no localStorage/sessionStorage, transient closure only.

## DoD

`BrowserSessionLLM` completes a real call via the lawyer's Claude.ai/ChatGPT session.
The selector retuning against live DOM is the manual smoke step above; the unit tests
cover the extraction logic so a UI change is caught early.
