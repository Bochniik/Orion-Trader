import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import PredictiveIntelligencePanel from "./PredictiveIntelligencePanel";

describe("PredictiveIntelligencePanel", () => {
  it("renders an assistant-only probability workspace with explicit no-certainty language", () => {
    const html = renderToStaticMarkup(
      <PredictiveIntelligencePanel alpacaConnected={false} />
    );

    expect(html).toContain("ORION PREDICTIVE INTELLIGENCE");
    expect(html).toContain("Probability, cost and liquidity—not certainty");
    expect(html).toContain("ASSISTANT ONLY");
    expect(html).toContain("Build / validate baseline");
    expect(html).toContain("Liquidity-first market");
    expect(html).toContain("Chosen stock");
    expect(html.includes("One-minute history is never relabeled")).toBe(false);
    expect(html).not.toContain("Submit order");
  });
});
