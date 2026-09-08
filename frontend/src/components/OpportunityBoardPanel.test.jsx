import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import OpportunityBoardPanel from "./OpportunityBoardPanel";


describe("OpportunityBoardPanel", () => {
  it("offers connected broker universes without implying exhaustive AI calls", () => {
    const html = renderToStaticMarkup(<OpportunityBoardPanel
      alpacaConnected={false}
      trading212Connected
      activeSource="trading212_demo"
      onOpenTicker={() => {}}
      onOpenBroker={() => {}}
    />);

    expect(html).toContain("Tradable universe");
    expect(html).toContain("Automatic · Trading 212 Demo");
    expect(html).toContain("Trading 212 Demo");
    expect(html).toContain("Alpaca Paper · disconnected");
    expect(html).toContain("bounded market-data batch");
    expect(html).toContain("Nothing here places an order");
    expect(html).toContain("All quality setups");
    expect(html).toContain("Entry-ready now");
    expect(html).toContain("Catalyst breakout radar");
    expect(html).toContain("rule score is not a probability");
    expect(html).toContain("It is not certainty");
  });
});
