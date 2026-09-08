import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import ExtremeMoveReplayPanel from "./ExtremeMoveReplayPanel";

describe("ExtremeMoveReplayPanel", () => {
  it("states the point-in-time, non-probabilistic research contract", () => {
    const html = renderToStaticMarkup(
      <ExtremeMoveReplayPanel initialTicker="SAVA" onOpenTicker={() => {}} />
    );

    expect(html).toContain("Test what Orion could have known before the move");
    expect(html).toContain("SAVA");
    expect(html).toContain("20% · 50% · 100%");
    expect(html).toContain("Feature cutoff enforced");
    expect(html).toContain("Not calibrated");
    expect(html).toContain("Run point-in-time replay");
    expect(html).toContain("Replay history");
  });
});
