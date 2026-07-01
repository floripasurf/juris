// Content script — runs in the Claude.ai/ChatGPT tab. Receives a (de-identified)
// CompletionRequest relayed from the native host via the background worker, drives
// the chat UI, and returns a CompletionResponse. The DOM details live in
// selectors.js so this file stays about flow + robustness.
//
// Security: the prompt must arrive already de-identified — and we ENFORCE that
// (assertCloudSafe below) rather than trust it, refusing raw PII before touching the
// DOM. Messages are accepted only from our own extension (isTrustedSender). We never
// persist the prompt — no localStorage/sessionStorage, just a transient closure GC'd
// after the reply.

import { providerFor, findComposer, isStreaming, extractResponse, detectBlocker } from "./selectors.js";

const TIMEOUT_MS = 120000; // hard cap on a single completion
const POLL_MS = 400;
const SETTLE_MS = 800; // text must hold steady (no streaming) this long before we trust it

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function fail(request_id, error) {
  return { request_id, success: false, content: null, error };
}

// --- Cloud-safe handshake (defense-in-depth) ---------------------------------
// The prompt must already be de-identified by the juris backend before it reaches
// the browser LLM. We ENFORCE that here rather than trusting the comment: a request
// must attest deidentified===true AND carry no raw structured PII. De-id placeholders
// ([CPF_1], [NOME_1]) are safe; raw structured PII means de-id failed, so we refuse.
// This list MIRRORS the backend de-id patterns (juris/core/deid.py) so the backstop is
// not narrower than the primary layer it's meant to catch regressions of.
const RAW_PII = [
  /\b\d{3}\.\d{3}\.\d{3}-\d{2}\b/, // CPF (formatted)
  /\b\d{2}\.\d{3}\.\d{3}\/\d{4}-\d{2}\b/, // CNPJ (formatted)
  /\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b/, // CNJ
  /\b\d{2}\.\d{3}\.\d{3}-[\dxX]\b/, // RG
  /\b[\w.+-]+@[\w-]+\.[\w.-]+\b/, // e-mail
  /\bOAB[/\s][A-Z]{2}\s*(?:n[º°.]?\s*)?\d/i, // OAB number (not the bare word "OAB")
  /\b\d{5}-\d{3}\b/, // CEP
  /(?<!\d)(?:\+55\s?)?(?:\(\d{2}\)\s?|\d{2}\s)?\d{4,5}-\d{4}(?!\d)/, // Brazilian phone
];

export function containsRawPII(text) {
  if (!text) return false;
  return RAW_PII.some((re) => re.test(text));
}

export function assertCloudSafe(request) {
  if (request?.deidentified !== true) {
    return "recusado: requisição sem atestado de de-identificação (deidentified)";
  }
  if (containsRawPII(`${request.system ?? ""}\n${request.prompt ?? ""}`)) {
    return "recusado: PII bruta detectada — a de-identificação falhou, não enviado à sessão";
  }
  return null;
}

// Only our OWN extension's background worker may drive the session — reject a message
// from any other extension (or an injected page script that reached this listener).
export function isTrustedSender(sender, runtimeId) {
  return !!sender && sender.id === runtimeId;
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

// Insert text into a (React) editor reliably: execCommand keeps the editor's own
// handling intact; the input event makes the framework register the change.
function insertPrompt(composer, text) {
  composer.focus();
  document.execCommand("insertText", false, text);
  composer.dispatchEvent(new InputEvent("input", { bubbles: true, data: text, inputType: "insertText" }));
}

// Prefer the send button (more reliable on modern UIs than a synthetic Enter).
function submit(composer, provider) {
  const btn = provider.sendButton ? document.querySelector(provider.sendButton) : null;
  if (btn && !btn.disabled) {
    btn.click();
    return;
  }
  composer.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
}

const BLOCKER_MESSAGES = {
  not_logged_in: "sessão não logada — faça login no Claude.ai/ChatGPT",
  rate_limited: "limite de uso da sessão atingido — tente mais tarde",
};

async function complete(request) {
  const { request_id, prompt, system } = request;
  // Enforce the de-id handshake BEFORE touching the DOM: never let raw PII reach
  // the browser LLM, even if the backend de-id regressed.
  const unsafe = assertCloudSafe(request);
  if (unsafe) return fail(request_id, unsafe);

  const provider = providerFor(location.host);
  if (!provider) return fail(request_id, "provedor não suportado nesta aba");

  const blocker = detectBlocker(document, provider);
  if (blocker) return fail(request_id, BLOCKER_MESSAGES[blocker]);

  const composer = findComposer(document, provider);
  // Login was already ruled out by detectBlocker above, so a missing composer means the
  // provider's DOM changed (its selectors moved) — a distinct, actionable status.
  if (!composer) return fail(request_id, "dom_changed: composer não encontrado (a interface do provedor mudou)");

  try {
    const full = system ? `${system}\n\n${prompt}` : prompt;
    insertPrompt(composer, full);
    submit(composer, provider);
    const result = await waitForCompletion(provider, request_id);
    if (!result.success) {
      // a usage limit can appear mid-generation — report it precisely
      const post = detectBlocker(document, provider);
      if (post) return fail(request_id, BLOCKER_MESSAGES[post]);
    }
    return result;
  } catch (e) {
    return fail(request_id, `falha ao injetar/extrair: ${e?.message ?? e}`);
  }
}

// Health/handshake — the orchestrator pings before sending work so the console can
// show a clear status: conectado (ready) / precisa login / DOM mudou / rate-limited.
export function connectionStatus(doc, host) {
  const provider = providerFor(host);
  if (!provider) return { connected: false, provider: null, status: "unsupported" };
  const blocker = detectBlocker(doc, provider); // not_logged_in | rate_limited | null
  if (blocker) return { connected: true, provider: host, status: blocker };
  return { connected: true, provider: host, status: findComposer(doc, provider) ? "ready" : "dom_changed" };
}

// Background worker relays the request here and awaits the response.
if (typeof chrome !== "undefined" && chrome.runtime?.onMessage) {
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    // Reject anything not sent by our own extension's background worker.
    if (!isTrustedSender(sender, chrome.runtime.id)) return false;
    if (msg?.type === "ping") {
      sendResponse(connectionStatus(document, location.host));
      return true;
    }
    if (msg?.type !== "completion") return false;
    complete(msg.request).then(sendResponse);
    return true; // async response
  });
}

// Exported for unit tests (selectors.test.js covers the DOM bits directly).
export { complete, waitForCompletion };
