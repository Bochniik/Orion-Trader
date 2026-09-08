export const PRODUCT_MODE = Object.freeze({
  label: "Decision support",
  realOrderExecution: false,
  liveCredentialsAccepted: false,
  executionBoundary: "Real orders are reviewed and executed in an external broker.",
});

export const ASSISTANT_PILLARS = Object.freeze([
  "Evidence before action",
  "Risk before reward",
  "Human owns the decision",
]);

export const EXECUTION_HANDOFF_STEPS = Object.freeze([
  {
    number: "01",
    title: "Research",
    detail: "Use market data, news, technicals and Orion to build the case.",
  },
  {
    number: "02",
    title: "Validate",
    detail: "Define position size, invalidation, risk and the evidence still missing.",
  },
  {
    number: "03",
    title: "Execute externally",
    detail: "Place any real-money order yourself in the regulated broker you choose.",
  },
  {
    number: "04",
    title: "Journal",
    detail: "Record the thesis and outcome so Orion can review the process later.",
  },
]);
