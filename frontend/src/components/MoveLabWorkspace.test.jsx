import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import MoveLabWorkspace from "./MoveLabWorkspace";

describe("MoveLabWorkspace", () => {
  it("keeps live scanning, replay and execution stress as separate modes", () => {
    const html = renderToStaticMarkup(<MoveLabWorkspace
      ticker="AAPL"
      alpacaConnected={false}
      trading212Connected={false}
      activeSource="local"
    />);

    expect(html).toContain("Live Scanner");
    expect(html).toContain("Replay Lab");
    expect(html).toContain("Execution Lab");
    expect(html).toContain("Current preparation, ignition and danger");
    expect(html).toContain("Historical 20%, 50% and 100% outcomes");
    expect(html).toContain("Spread, gaps, fills, pauses and rejection");
    expect(html).toContain("Find preparation, confirm ignition, reject danger");
  });
});
