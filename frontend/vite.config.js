import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// One automatic JSX runtime for dev, production and Vitest; no window.React.
export default defineConfig({ plugins: [react()] });
