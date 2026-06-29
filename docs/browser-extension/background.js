// Background service worker — bridges the native host (the juris local agent) and
// the content script in the Claude.ai/ChatGPT tab.
//
//   juris agent  ⇄  native host (com.juris.host)  ⇄  [this]  →  content.js  →  chat UI
//
// The host sends a CompletionRequest; we relay it to the provider tab and post the
// content script's CompletionResponse back. Nothing is persisted here.

const HOST = "com.juris.host";
let port = null;

function connect() {
  port = chrome.runtime.connectNative(HOST);
  port.onMessage.addListener(onHostMessage);
  port.onDisconnect.addListener(() => {
    port = null; // Chrome restarts the worker on the next message
  });
}

async function findProviderTab() {
  const tabs = await chrome.tabs.query({
    url: ["https://claude.ai/*", "https://chatgpt.com/*"],
  });
  return tabs[0] ?? null;
}

async function onHostMessage(request) {
  const reply = (resp) => port?.postMessage(resp);
  const tab = await findProviderTab();
  if (!tab) {
    reply({
      request_id: request.request_id,
      success: false,
      content: null,
      error: "nenhuma aba Claude.ai/ChatGPT aberta",
    });
    return;
  }
  chrome.tabs.sendMessage(tab.id, { type: "completion", request }, (resp) => {
    reply(
      resp ?? {
        request_id: request.request_id,
        success: false,
        content: null,
        error: "sem resposta do content script (recarregue a aba)",
      },
    );
  });
}

connect();
