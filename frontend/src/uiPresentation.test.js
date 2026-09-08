import { describe, expect, it } from "vitest";

import {
  ASSISTANT_PILLARS,
  EXECUTION_HANDOFF_STEPS,
  PRODUCT_MODE,
} from "./uiPresentation";

describe("assistant-only product presentation", () => {
  it("keeps real-money execution and Live credentials outside OrionTrader", () => {
    expect(PRODUCT_MODE.realOrderExecution).toBe(false);
    expect(PRODUCT_MODE.liveCredentialsAccepted).toBe(false);
    expect(PRODUCT_MODE.executionBoundary).toMatch(/external broker/i);
  });

  it("presents a complete research-to-journal handoff", () => {
    expect(EXECUTION_HANDOFF_STEPS.map((step) => step.title)).toEqual([
      "Research",
      "Validate",
      "Execute externally",
      "Journal",
    ]);
    expect(ASSISTANT_PILLARS).toContain("Human owns the decision");
  });
});
