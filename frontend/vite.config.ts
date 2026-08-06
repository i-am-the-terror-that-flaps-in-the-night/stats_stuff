import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend (Backend/app.py) serves the built bundle in production and the
// JSON API in every environment. Two things this config has to get right:
//
//   base: "/"   -- ABSOLUTE asset URLs, and this is not a free choice. Relative
//                  ones ("./assets/…") look tempting for previewing the build off
//                  disk, but they break a router with nested routes: index.html is
//                  served for every deep link, so from /studio/runs the browser
//                  resolves "./assets/index.js" against /studio/ and 404s. No JS
//                  loads, and the page is blank -- silently, since the HTML itself
//                  returned 200. Absolute paths resolve identically at every depth.
//
//                  Previewing therefore means `npm run dev` (below) or serving
//                  dist/ from its own root, not opening dist/index.html directly.
//
//   proxy       -- in `npm run dev`, Vite serves the app on :5173 while uvicorn
//                  holds the API on :8000. Proxying the API paths keeps the
//                  browser on one origin, so there is no CORS in development and
//                  the client can just call "/api/…" exactly as it does in prod.
export default defineConfig({
  base: "/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    // Fail the build rather than ship a silently oversized bundle.
    chunkSizeWarningLimit: 600,
    sourcemap: true,
  },
});
