import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import ExecutionSimulationPanel from "./ExecutionSimulationPanel";

describe("ExecutionSimulationPanel", () => {
  it("states the deterministic, zero-order execution research contract", () => {
    const html = renderToStaticMarkup(<ExecutionSimulationPanel initialTicker="SAVA" />);

    expect(html).toContain("Find out whether a good chart survives a bad fill");
    expect(html).toContain("SAVA");
    expect(html).toContain("Deterministic matrix");
    expect(html).toContain("No queue-priority fiction");
    expect(html).toContain("ZERO ORDER ROUTES");
    expect(html).toContain("Run stress matrix");
    expect(html).toContain("Execution Lab history");
  });
});
