import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Website has its own node_modules; dedupe React so hooks share one instance.
  resolve: { dedupe: ["react", "react-dom"] },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: [
      "src/**/*.test.tsx",
      "src/**/*.test.ts",
      "website/src/**/*.test.ts",
      "website/src/**/*.test.tsx",
    ],
    exclude: ["node_modules", "dist"],
  },
});
