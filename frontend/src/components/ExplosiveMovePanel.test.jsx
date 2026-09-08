import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import ExplosiveMovePanel from "./ExplosiveMovePanel";

describe("ExplosiveMovePanel", () => {
  it("keeps preparation, ignition and danger distinct and fail-closed", () => {
    const html = renderToStaticMarkup(<ExplosiveMovePanel
      alpacaConnected
      trading212Connected={false}
      activeSource="alpaca"
      onOpenTicker={() => {}}
      onOpenBroker={() => {}}
    />);

    expect(html).toContain("Find preparation, confirm ignition, reject danger");
    expect(html).toContain("PreMoveScore");
    expect(html).toContain("IgnitionScore");
    expect(html).toContain("DangerScore");
    expect(html).toContain("None is a probability or a buy signal");
    expect(html).toContain("RESEARCH / SHADOW ONLY");
    expect(html).toContain("No order route");
    expect(html).toContain("WebSocket not active");
    expect(html).toContain("Live Alpaca evidence");
    expect(html).toContain("Research evidence only");
    expect(html).toContain("Start live evidence");
    expect(html).toContain("Danger rejection threshold");
  });
});
