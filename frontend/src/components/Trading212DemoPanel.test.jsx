import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import Trading212DemoPanel from "./Trading212DemoPanel";


describe("Trading212DemoPanel", () => {
  it("makes the Demo and manual-confirmation boundary unmistakable", () => {
    const html = renderToStaticMarkup(<Trading212DemoPanel />);

    expect(html).toContain("Trading 212 Demo portfolio");
    expect(html).toContain("DEMO · MANUAL CONFIRM");
    expect(html).toContain("every order and cancellation requires your click");
    expect(html).toContain("no Live or autonomous Trading 212 route exists");
    expect(html).not.toContain("Trading 212 Live");
  });
});
