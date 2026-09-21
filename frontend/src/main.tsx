import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { BootLoader } from "./components/BootLoader";
// Self-hosted type, bundled by Vite -- no CDN, nothing fetched from a third
// party at runtime. The three faces of the Observatory system: Young Serif for
// display, Sora for reading, Martian Mono for numbers.
import "@fontsource/young-serif/latin-400.css";
import "@fontsource-variable/sora/wght.css";
import "@fontsource-variable/martian-mono/wght.css";
import "./styles/styles.css";

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error('Missing #root — check index.html');

createRoot(rootEl).render(
  <StrictMode>
    <BootLoader>
      <App />
    </BootLoader>
  </StrictMode>,
);
