import { describe, expect, it } from "vitest";
import { DEEP_DIVES, HORIZON_GUIDES, STRATEGIES, STRATEGY_DETAILS, TERMS } from "./LearningCenterPanel";

describe("Orion learning-center content", () => {
  it("includes the key concepts used by charts and autonomy decisions", () => {
    const names = TERMS.map((item) => item.term);
    expect(names).toEqual(expect.arrayContaining([
      "EMA", "SMA", "RSI", "Volume", "Decision confidence", "risk_rejected",
    ]));
    expect(new Set(names).size).toBe(names.length);
  });

  it("explains each strategy with confirmation, invalidation and a common trap", () => {
    expect(STRATEGIES.length).toBeGreaterThanOrEqual(5);
    for (const strategy of STRATEGIES) {
      expect(strategy.confirmation).toBeTruthy();
      expect(strategy.invalidation).toBeTruthy();
      expect(strategy.trap).toBeTruthy();
      expect(STRATEGY_DETAILS[strategy.name]?.process).toBeTruthy();
      expect(STRATEGY_DETAILS[strategy.name]?.risk).toBeTruthy();
      expect(STRATEGY_DETAILS[strategy.name]?.exit).toBeTruthy();
    }
  });

  it("provides mechanics, examples, and context for every glossary term", () => {
    for (const item of TERMS) {
      expect(DEEP_DIVES[item.term]?.mechanics).toBeTruthy();
      expect(DEEP_DIVES[item.term]?.example).toBeTruthy();
      expect(DEEP_DIVES[item.term]?.combine).toBeTruthy();
    }
    expect(HORIZON_GUIDES.map((item) => item.name)).toEqual([
      "Day trading", "Swing trading", "Long-term investing",
    ]);
  });
});
