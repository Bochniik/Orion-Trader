import { readFileSync } from "node:fs";
import vm from "node:vm";
import { expect, it } from "vitest";

it("does not cache authenticated APIs, cross-origin data or arbitrary pages", () => {
  const handlers = {};
  const code = readFileSync(new URL("../../public/sw.js", import.meta.url), "utf8");
  vm.runInNewContext(code, {
    self: { location: { origin: "https://orion.test" }, addEventListener: (name, handler) => { handlers[name] = handler; } }, URL,
  });
  for (const url of ["https://orion.test/api/portfolio/active", "https://orion.test/auth/session", "http://127.0.0.1:8000/quote/AAPL", "https://orion.test/user-data"]) {
    let intercepted = false;
    handlers.fetch({ request: { url, method: "GET" }, respondWith: () => { intercepted = true; } });
    expect(intercepted).toBe(false);
  }
});
