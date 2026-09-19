import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { SessionResearchWorkspace } from "./TodayView";
import { getCoreSession } from "../api/api";


describe("Orion 24/7 session experience", () => {
  it("renders closed-market research instead of an empty live surface", () => {
    const html = renderToStaticMarkup(
      <SessionResearchWorkspace
        session={{
          mode: "closed",
          status: "next_session_research",
          next_open: "2026-09-21T13:30:00+00:00",
          price_semantics: "historical_or_delayed",
          allowed_workflows: { settlement_and_evaluation: true },
          warnings: [],
        }}
        watchlistCount={7}
      />
    );

    expect(html).toContain("ORION 24/7 INTELLIGENCE");
    expect(html).toContain("Research &amp; preparation");
    expect(html).toContain("Watchlist research queue");
    expect(html).toContain(">7<");
    expect(html).toContain("ACTIVE");
    expect(html).toContain("HISTORICAL OR DELAYED");
    expect(html).toContain("never labelled as live regular-session data");
  });

  it("does not render the research workspace during the regular session", () => {
    const html = renderToStaticMarkup(
      <SessionResearchWorkspace
        session={{ mode: "regular", status: "regular_session" }}
        watchlistCount={4}
      />
    );
    expect(html).toBe("");
  });

  it("uses the authenticated core session endpoint", async () => {
    const response = {
      ok: true,
      status: 200,
      headers: { get: () => "application/json" },
      json: async () => ({ mode: "closed" }),
      text: async () => "",
    };
    global.fetch = vi.fn().mockResolvedValue(response);

    await getCoreSession();

    expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/core/session",
      expect.objectContaining({ credentials: "include" })
    );
  });
});
