// Routes. Replaces both the multi-document site (Web/HTML/*.html + nav.js) and
// the server-rendered Studio pages (Backend/templates/studio/*.html).
//
// One route per file under routes/, each built from the same primitives in
// components/Page.tsx.

import type { JSX } from "react";
import { createBrowserRouter, RouterProvider } from "react-router";
import { Shell } from "./components/Shell";
import { Overview } from "./routes/Overview";
import { Methodology } from "./routes/Methodology";
import { Benchmarks } from "./routes/Benchmarks";
import { Changelog } from "./routes/Changelog";
import { Downloads } from "./routes/Downloads";
import { Figures } from "./routes/Figures";
import { Study } from "./routes/Study";
import { StudioIndex } from "./routes/StudioIndex";
import { StudioExperiments } from "./routes/StudioExperiments";
import { StudioAnalyze } from "./routes/StudioAnalyze";
import { StudioRuns } from "./routes/StudioRuns";
import { Guide } from "./routes/Guide";
import { NotFound } from "./routes/NotFound";

const router = createBrowserRouter([
  {
    path: "/",
    element: <Shell />,
    children: [
      { index: true, element: <Overview /> },
      { path: "study", element: <Study /> },
      { path: "figures", element: <Figures /> },
      { path: "downloads", element: <Downloads /> },
      { path: "methodology", element: <Methodology /> },
      { path: "benchmarks", element: <Benchmarks /> },
      { path: "changelog", element: <Changelog /> },
      { path: "studio", element: <StudioIndex /> },
      { path: "studio/experiments", element: <StudioExperiments /> },
      { path: "studio/analyze/:tier/:column", element: <StudioAnalyze /> },
      { path: "studio/runs", element: <StudioRuns /> },
      { path: "guide", element: <Guide /> },
      { path: "*", element: <NotFound /> },
    ],
  },
]);

export function App(): JSX.Element {
  return <RouterProvider router={router} />;
}
