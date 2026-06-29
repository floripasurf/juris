// Content script — runs in the Claude.ai/ChatGPT tab. Receives a (de-identified)
// CompletionRequest relayed from the native host via the background worker, drives
// the chat UI, and returns a CompletionResponse. The DOM details live in
// selectors.js so this file stays about flow + robustness.
//
// Security: the prompt arrives already de-identified (juris de-id runs before the
// bridge). We never persist it — no localStorage/sessionStorage, just a transient
// closure that is GC'd after the reply.

import { providerFor, findComposer, isStreaming, extractResponse } from "./selectors.js";

const TIMEOUT_MS = 120000; // hard cap on a single completion
const POLL_MS = 400;
const SETTLE_MS = 800; // text must hold steady (no streaming) this long before we trust it

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function fail(request_id, error) {
  return { request_id, success: false, content: null, error };
}

// Resolve only when generation has stopped AND the text is non-empty and stable.
// A partial/streaming answer is NEVER returned as success.
async function waitForCompletion(provider, request_id) {
  const start = Date.now();
  let lastText = null;
  let settledSince = null;

  while (Date.now() - start < TIMEOUT_MS) {
    await sleep(POLL_MS);

    if (isStreaming(document, provider)) {
      settledSince = null;
      lastText = extractResponse(document, provider);
      continue;
    }

    const text = extractResponse(document, provider);
    if (!text) continue; // not streaming but nothing yet — keep waiting

    if (text === lastText) {
      settledSince ??= Date.now();
      if (Date.now() - settledSince >= SETTLE_MS) {
        return { request_id, success: true, content: text, error: null };
      }
    } else {
      lastText = text;
      settledSince = null;
    }
  }
  return fail(request_id, "timeout aguardando a resposta finalizar");
}

async function complete({ request_id, prompt, system }) {
  const provider = providerFor(location.host);
  if (!provider) return fail(request_id, "provedor não suportado nesta aba");

  const composer = findComposer(document, provider);
  if (!composer) return fail(request_id, "composer não encontrado — faça login na sessão");

  try {
    composer.focus();
    const full = system ? `${system}\n\n${prompt}` : prompt;
    // insertText keeps the editor's own input handling intact
    document.execCommand("insertText", false, full);
    composer.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    return await waitForCompletion(provider, request_id);
  } catch (e) {
    return fail(request_id, `falha ao injetar/extrair: ${e?.message ?? e}`);
  }
}

// Background worker relays the request here and awaits the response.
if (typeof chrome !== "undefined" && chrome.runtime?.onMessage) {
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.type !== "completion") return false;
    complete(msg.request).then(sendResponse);
    return true; // async response
  });
}

// Exported for unit tests (selectors.test.js covers the DOM bits directly).
export { complete, waitForCompletion };
