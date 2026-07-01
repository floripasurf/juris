import { describe, it, expect } from "vitest";
import { JSDOM } from "jsdom";
import { connectionStatus } from "./content.js";

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
