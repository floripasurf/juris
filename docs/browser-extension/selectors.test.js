// Unit tests for the provider selectors/parsers (DOM fixture via jsdom).
// These cover the brittle part — the DOM extraction — so a UI change is caught
// here and retuned in one place. The live integration is the manual Chrome smoke.
import { describe, it, expect } from "vitest";
import { providerFor, findComposer, isStreaming, extractResponse } from "./selectors.js";

describe("providerFor", () => {
  it("maps hosts to providers", () => {
    expect(providerFor("claude.ai")).toBeTruthy();
    expect(providerFor("chatgpt.com")).toBeTruthy();
    expect(providerFor("chat.openai.com")).toBeTruthy();
    expect(providerFor("example.com")).toBeNull();
  });
});

describe("claude.ai DOM", () => {
  const provider = providerFor("claude.ai");

  it("finds the composer", () => {
    document.body.innerHTML = `<div contenteditable="true" class="ProseMirror"></div>`;
    expect(findComposer(document, provider)).not.toBeNull();
  });

  it("returns null composer when not logged in", () => {
    document.body.innerHTML = `<div class="login-wall">Faça login</div>`;
    expect(findComposer(document, provider)).toBeNull();
  });

  it("extracts the last assistant message", () => {
    document.body.innerHTML = `
      <div class="font-claude-message">primeira resposta</div>
      <div class="font-claude-message">resposta final do modelo</div>`;
    expect(extractResponse(document, provider)).toBe("resposta final do modelo");
  });

  it("detects streaming via the stop button", () => {
    document.body.innerHTML = `<button aria-label="Stop response"></button>`;
    expect(isStreaming(document, provider)).toBe(true);
    document.body.innerHTML = `<button aria-label="Send message"></button>`;
    expect(isStreaming(document, provider)).toBe(false);
  });

  it("returns null when there is no response yet", () => {
    document.body.innerHTML = `<div class="font-claude-message">   </div>`;
    expect(extractResponse(document, provider)).toBeNull();
  });
});

describe("chatgpt.com DOM", () => {
  const provider = providerFor("chatgpt.com");

  it("extracts the last assistant message", () => {
    document.body.innerHTML = `
      <div data-message-author-role="user">pergunta</div>
      <div data-message-author-role="assistant">resposta do gpt</div>`;
    expect(extractResponse(document, provider)).toBe("resposta do gpt");
  });
});
