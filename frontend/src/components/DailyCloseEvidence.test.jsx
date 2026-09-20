import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import DailyCloseEvidence from "./DailyCloseEvidence";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("DailyCloseEvidence", () => {
  it("renders only settled metrics returned by the daily review endpoint", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ session_date: "2026-09-18", sample_size: 12, directional_accuracy: 0.75, brier_score: 0.18, log_loss: 0.54, false_positives: 1, false_negatives: 2 }),
    }));
    render(<DailyCloseEvidence />);
    await waitFor(() => expect(screen.getByTestId("daily-close-evidence")).toBeTruthy());
    expect(screen.getByText("75.0%")).toBeTruthy();
    expect(screen.getByText("12 resolved")).toBeTruthy();
  });

  it("fails closed when no settled evidence exists", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ sample_size: 0 }) }));
    render(<DailyCloseEvidence />);
    await waitFor(() => expect(screen.getByTestId("daily-close-evidence-empty")).toBeTruthy());
    expect(screen.queryByText("0.0%")).toBeNull();
  });
});
