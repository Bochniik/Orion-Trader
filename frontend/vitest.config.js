import { defineConfig } from "vitest/config";

// Vitest 4 embeds Vite 7/esbuild; the production Vite 8 uses Oxc via plugin-react.
// Keep both on React's automatic runtime, rather than relying on a global React.
export default defineConfig({ esbuild: { jsx: "automatic" } });
