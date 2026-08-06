import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { BootLoader } from "./components/BootLoader";
import "./styles/styles.css";
import "./styles/studio.css";

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error('Missing #root — check index.html');

createRoot(rootEl).render(
  <StrictMode>
    <BootLoader>
      <App />
    </BootLoader>
  </StrictMode>,
);
