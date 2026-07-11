// Unit tests for the background service worker's tab routing (spec 2026-07-05):
// the declared provider must drive which chat tab receives the prompt.
import { describe, it, expect, afterEach } from "vitest";
import { findProviderTab } from "./background.js";

function stubTabs(byUrl) {
  // chrome.tabs.query({ url: [...] }) → tabs matching ANY of the url patterns.
  globalThis.chrome = {
    tabs: {
      query: async ({ url }) => {
        const patterns = Array.isArray(url) ? url : [url];
        return patterns.flatMap((p) => byUrl[p] ?? []);
      },
    },
  };
}

describe("findProviderTab", () => {
  afterEach(() => {
    delete globalThis.chrome;
  });

  it("routes to the declared provider's tab when open", async () => {
    stubTabs({
      "https://claude.ai/*": [{ id: 1 }],
      "https://chatgpt.com/*": [{ id: 2 }],
    });
    expect((await findProviderTab("chatgpt")).id).toBe(2);
    expect((await findProviderTab("claude")).id).toBe(1);
  });

  it("falls back to any supported tab when the preferred is not open", async () => {
    stubTabs({ "https://claude.ai/*": [{ id: 1 }] }); // only Claude open
    // declared chatgpt, but only a Claude tab exists → fall back (divergence warning fires server-side)
    expect((await findProviderTab("chatgpt")).id).toBe(1);
  });

  it("uses any supported tab when no preference is declared", async () => {
    stubTabs({ "https://chatgpt.com/*": [{ id: 7 }] });
    expect((await findProviderTab(null)).id).toBe(7);
  });

  it("returns null when no supported tab is open", async () => {
    stubTabs({});
    expect(await findProviderTab("claude")).toBeNull();
  });
});
