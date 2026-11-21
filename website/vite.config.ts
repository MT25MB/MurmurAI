import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// GitHub Pages serves project sites at /<repo-name>/. Keep this in sync with
// the repository name (see config.ts REPO_SLUG).
export default defineConfig({
  base: "/MurmurAI/",
  plugins: [react(), tailwindcss()],
  build: { outDir: "dist" },
});
