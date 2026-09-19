import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import StockNewsPanel from "./StockNewsPanel";


describe("StockNewsPanel Orion insights", () => {
  const news = [{
    title: "AAPL launches a new product",
    publisher: "Example News",
    link: "https://example.com/aapl",
    published_at: 1789812000,
    summary: "Apple announced a product update with new availability details.",
  }];

  it("renders Orion sentiment, digest and evidence scope beside the loaded article", () => {
    const html = renderToStaticMarkup(
      <StockNewsPanel
        ticker="AAPL"
        news={news}
        loading={false}
        error=""
        onRefresh={() => {}}
        insights={{
          "0": {
            article_id: "0",
            sentiment: "POSITIVE",
            summary: "The supplied news describes a product launch.",
            key_points: ["A new product was announced.", "Availability details were included."],
            why_it_matters: "The launch may affect the company narrative.",
            evidence_scope: "headline_and_summary",
          },
        }}
      />
    );

    expect(html).toContain("ORION TAKE");
    expect(html).toContain("POSITIVE");
    expect(html).toContain("headline + summary");
    expect(html).toContain("The supplied news describes a product launch.");
    expect(html).toContain("A new product was announced.");
    expect(html).toContain("Why it matters:");
  });

  it("shows a non-blocking Orion loading state while keeping the article visible", () => {
    const html = renderToStaticMarkup(
      <StockNewsPanel
        ticker="AAPL"
        news={news}
        loading={false}
        error=""
        onRefresh={() => {}}
        insightsLoading
      />
    );

    expect(html).toContain("AAPL launches a new product");
    expect(html).toContain("Orion is reviewing the loaded headlines");
    expect(html).toContain("Reviewing sentiment and extracting the key information");
  });
});
