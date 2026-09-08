import { describe, expect, it } from "vitest";
import { currentDecision } from "./decisionPresentation";
import { normalizeCoreResult } from "./coreJobClient";

describe("analysis regression guards", () => {
  it("renders a non-actionable result safely when direction is missing", () => {
    const result = currentDecision({ symbol: "IONQ", actionable: false, direction: null, status: null });

    expect(result.ticker).toBe("IONQ");
    expect(result.direction).toBe("WAIT");
    expect(result.status).toBe("unknown");
    expect(result.reasons).toEqual([]);
    expect(result.warnings).toEqual([]);
  });

  it("does not let strategy bias replace the final Orion decision", () => {
    const result = normalizeCoreResult({
      ticker: "RGTI",
      direction: "WAIT",
      bias: "bearish",
      reasons: [],
      warnings: [],
    });

    expect(result.direction).toBe("WAIT");
    expect(result.bias).toBe("WAIT");
    expect(result.strategy_bias).toBe("bearish");
  });

  it("preserves a genuine final bearish direction", () => {
    const result = normalizeCoreResult({ ticker: "AAPL", direction: "SHORT", bias: "bearish" });

    expect(result.direction).toBe("SHORT");
    expect(result.bias).toBe("SHORT");
    expect(result.strategy_bias).toBe("bearish");
  });
});
