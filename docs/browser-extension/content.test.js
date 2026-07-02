import { describe, it, expect } from "vitest";
import { JSDOM } from "jsdom";
import { connectionStatus, containsRawPII, assertCloudSafe, isTrustedSender } from "./content.js";

function docWith(html) {
  return new JSDOM(`<!doctype html><body>${html}</body>`).window.document;
}

describe("connectionStatus (handshake)", () => {
  it("reports ready when the composer is present", () => {
    const doc = docWith('<div contenteditable="true"></div>');
    const s = connectionStatus(doc, "claude.ai");
    expect(s.connected).toBe(true);
    expect(s.status).toBe("ready");
  });

  it("reports not_logged_in behind a login wall", () => {
    const doc = docWith('<a href="/login">Log in</a>');
    expect(connectionStatus(doc, "claude.ai").status).toBe("not_logged_in");
  });

  it("reports dom_changed when logged in but the composer is gone", () => {
    const doc = docWith("<div>alguma UI nova</div>");
    expect(connectionStatus(doc, "claude.ai").status).toBe("dom_changed");
  });

  it("reports unsupported on an unknown host", () => {
    expect(connectionStatus(docWith(""), "example.com").connected).toBe(false);
  });
});

describe("de-id enforcement (cloud-safe handshake)", () => {
  it("flags raw CPF / CNPJ / e-mail / CNJ / OAB / RG / CEP / phone as PII", () => {
    expect(containsRawPII("CPF 123.456.789-09")).toBe(true);
    expect(containsRawPII("CPF 12345678909")).toBe(true);
    expect(containsRawPII("CNPJ 12.345.678/0001-90")).toBe(true);
    expect(containsRawPII("CNPJ 11222333000181")).toBe(true);
    expect(containsRawPII("contato joao@escritorio.adv.br")).toBe(true);
    expect(containsRawPII("processo 5082351-40.2017.8.13.0024")).toBe(true);
    expect(containsRawPII("processo 50823514020178130024")).toBe(true);
    expect(containsRawPII("OAB/MG 123456")).toBe(true);
    // These were silently passing before the backstop was aligned with the backend de-id.
    expect(containsRawPII("RG 12.345.678-9")).toBe(true);
    expect(containsRawPII("CEP 88010-400")).toBe(true);
    expect(containsRawPII("telefone (11) 91234-5678")).toBe(true);
  });

  it("treats de-identified placeholders (and the bare word OAB) as safe", () => {
    expect(
      containsRawPII("Autor [NOME_1], CPF [CPF_1], RG [RG_1], CEP [CEP_1], tel [TELEFONE_1], OAB sob [OAB_1]"),
    ).toBe(false);
  });

  it("does not treat arbitrary unformatted numbers as raw CPF/CNPJ/CNJ", () => {
    expect(containsRawPII("pedido 12345678901, contrato 11111111111")).toBe(false);
    expect(containsRawPII("nota 12345678901234, lote 12345678901234567890")).toBe(false);
    expect(containsRawPII("pedido 11111111111 e CPF 12345678909")).toBe(true);
  });

  it("refuses a request without the deidentified attestation", () => {
    expect(assertCloudSafe({ prompt: "oi", deidentified: false })).toMatch(/de-identifica/i);
    expect(assertCloudSafe({ prompt: "oi" })).toMatch(/de-identifica/i);
  });

  it("refuses a request that still carries raw PII even if flagged", () => {
    expect(assertCloudSafe({ prompt: "réu CPF 123.456.789-09", deidentified: true })).toMatch(/PII bruta/i);
  });

  it("allows a properly de-identified request", () => {
    expect(assertCloudSafe({ prompt: "Autor [NOME_1] pede…", system: "", deidentified: true })).toBeNull();
  });
});

describe("message sender validation", () => {
  it("accepts only messages from our own extension", () => {
    expect(isTrustedSender({ id: "abc" }, "abc")).toBe(true);
    expect(isTrustedSender({ id: "evil" }, "abc")).toBe(false);
    expect(isTrustedSender(undefined, "abc")).toBe(false);
    expect(isTrustedSender({}, "abc")).toBe(false);
  });
});
