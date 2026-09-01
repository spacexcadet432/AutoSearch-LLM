import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import tailwindcss from "@tailwindcss/vite";
import { nitro } from "nitro/vite";
import { defineConfig } from "vite";
import viteReact from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";

/**
 * Vercel-compatible TanStack Start build (Nitro).
 * Replaces Lovable-only config so Vercel can deploy the app (fixes blank/404 deploys).
 */
export default defineConfig({
  server: {
    port: 3000,
  },
  plugins: [
    tsconfigPaths(),
    tailwindcss(),
    tanstackStart({
      srcDirectory: "src",
      // Avoid prerender issues with Nitro Vercel preset (TanStack + Nitro guidance).
      prerender: { enabled: false },
    }),
    viteReact(),
    nitro({ preset: "vercel" }),
  ],
});
