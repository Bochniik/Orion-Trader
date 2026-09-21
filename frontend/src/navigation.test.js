import { describe, expect, it } from "vitest";
import { isWorkspaceView, viewFromHash, WORKSPACE_VIEWS } from "./navigation";

describe("workspace navigation", () => {
  it("maps valid deep links to their workspace section", () => {
    expect(viewFromHash("#/analyze")).toBe("analyze");
    expect(viewFromHash("#my-stocks")).toBe("my-stocks");
    expect(viewFromHash("#/intelligence")).toBe("intelligence");
  });

  it("falls back safely for unknown or empty links", () => {
    expect(viewFromHash("#/not-a-view")).toBe("today");
    expect(viewFromHash()).toBe("today");
  });

  it("exposes the four primary workflows", () => {
    const ids = WORKSPACE_VIEWS.map((view) => view.id);
    expect(ids).toEqual(["today", "analyze", "intelligence", "my-stocks"]);
    expect(new Set(ids).size).toBe(ids.length);
    expect(isWorkspaceView("analyze")).toBe(true);
    expect(isWorkspaceView("intelligence")).toBe(true);
    expect(isWorkspaceView("live-edge")).toBe(false);
    expect(isWorkspaceView("settings")).toBe(false);
  });
  it("migrates old bookmarks without re-exposing labs or trading controls", () => {
    expect(viewFromHash("#/research")).toBe("analyze");
    expect(viewFromHash("#/portfolio")).toBe("my-stocks");
    expect(viewFromHash("#/automation")).toBe("my-stocks");
    expect(viewFromHash("#/live-edge")).toBe("today");
    expect(viewFromHash("#/overview")).toBe("today");
  });
});
