// Downloads — every figure on the site, in one place, with the buttons made big.
//
// WHY THIS IS A PAGE AND NOT JUST THE CONTROL ON EACH FIGURE
//   The per-figure save control is the right thing when you are reading a figure
//   and decide you want it. It is the wrong thing when what you actually want is
//   "all of them, for the poster" — that means visiting two pages, opening ten
//   figures and answering ten save prompts. This page exists for that second
//   case: every figure rendered at once, one format choice, one file out.
//
// THE FIGURES HERE ARE REAL, NOT THUMBNAILS
//   Each tile draws the actual chart, because the exporter reads the live <svg>
//   out of the DOM — that is what makes a download match what is on screen. A
//   picture of a chart could not be exported as a vector PDF, and a second
//   "export-only" renderer would be a second thing to keep in step with the
//   first. So the tiles are the figures, at a size you can still read.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { JSX, ReactNode } from "react";
import { Crumbs, Masthead, Module, Status } from "../components/Page";
import type { SpecRow } from "../components/Page";
import { Picker } from "../components/figures/ChartFrame";
import { Histogram } from "../components/figures/Histogram";
import { EcdfChart } from "../components/figures/EcdfChart";
import { BoxPlot } from "../components/figures/BoxPlot";
import { ScatterPlot } from "../components/figures/ScatterPlot";
import { CorrelationHeatmap } from "../components/figures/CorrelationHeatmap";
import { DensityPlot } from "../components/figures/DensityPlot";
import { QQPlot } from "../components/figures/QQPlot";
import { ResidualPlot } from "../components/figures/ResidualPlot";
import { ForestPlot } from "../components/figures/ForestPlot";
import { DoseResponseChart } from "../components/figures/DoseResponseChart";
import {
  useBox,
  useCorrelation,
  useDensity,
  useDiagnostics,
  useFigureColumns,
  useHistogram,
  useScatter,
  useStudyStep,
} from "../lib/hooks";
import { figureBlob, figureName, saveBlob, slugify } from "../lib/svgExport";
import type { ExportFormat } from "../lib/svgExport";
import { zipBlob } from "../lib/zip";
import type { ZipEntry } from "../lib/zip";
import { labelOf } from "../lib/scales";
import { DIAGNOSTIC_MODELS } from "../types/engine";
import type { DirectEffectStep, DoseResponseStep } from "../types/engine";

const SPEC: SpecRow[] = [
  { k: "Figures", v: "10" },
  { k: "Formats", v: "PDF · PNG · SVG" },
  { k: "Vector", v: "PDF and SVG" },
  { k: "Bundle", v: "One .zip" },
];

/** What each format is actually for, said on the button rather than in a note. */
const FORMATS: { id: ExportFormat; label: string; note: string }[] = [
  { id: "pdf", label: "PDF", note: "Vector · for print" },
  { id: "png", label: "PNG", note: "Image · for slides" },
  { id: "svg", label: "SVG", note: "Vector · to edit" },
];

/** One tile: a figure, its name, and the three ways to take it away. */
interface Sheet {
  key: string;
  title: string;
  note: string;
  chart: ReactNode;
  /** Null while the data is still loading, or a message if it failed. */
  status: string | null;
}

export function Downloads(): JSX.Element {
  const { columns, categorical, error: columnsError } = useFigureColumns();

  const [column, setColumn] = useState<string | null>(null);
  const [group, setGroup] = useState("");
  const [against, setAgainst] = useState<string | null>(null);
  const [model, setModel] = useState<string>("direct-effect");

  // Four controls drive ten figures, so the defaults have to produce something
  // worth looking at rather than merely something valid: BMI against ALT is the
  // study's own exposure-adjacent pair, and a group split is chosen rather than
  // left empty because half these figures are comparisons and a box plot of one
  // undivided box says nothing. `?? null` on each fallback because indexing a
  // string[] is `string | undefined` under noUncheckedIndexedAccess.
  useEffect(() => {
    if (!columns.length) return;
    const pick = (preferred: string, fallback: number): string | null =>
      columns.includes(preferred) ? preferred : (columns[fallback] ?? null);
    setColumn((current) => current ?? pick("BMI", 0));
    setAgainst((current) => current ?? pick("ALT", 1));
  }, [columns]);

  useEffect(() => {
    if (group || !categorical.length) return;
    setGroup(categorical.includes("Sex") ? "Sex" : (categorical[0] ?? ""));
  }, [categorical, group]);

  const histogram = useHistogram(column);
  const box = useBox(column, group);
  // The scatter takes its x from the same Column control as everything else, so
  // one choice moves the whole page coherently instead of the reader having to
  // keep two column pickers in step by hand.
  const scatter = useScatter(column, against);
  const correlation = useCorrelation();
  const density = useDensity(column, group);
  const diagnostics = useDiagnostics(model);
  const doseStep = useStudyStep("dose-response");
  const primaryStep = useStudyStep("direct-effect");
  const dose = doseStep.step as DoseResponseStep | null;
  const primary = primaryStep.step as DirectEffectStep | null;

  const named = column ? labelOf(column) : "Column";
  // The slug, tidied — NOT the label the response carries. That label is a full
  // sentence ("Model B (full), BMI included: sugar's direct association…"), and
  // slugify would turn it into a sixty-character filename truncated mid-word.
  const modelLabel = model.replace(/-/g, " ");

  const sheets: Sheet[] = [
    {
      key: "hist",
      title: `${named} — distribution`,
      note: "How many people fall in each range of values.",
      chart: histogram.data ? <Histogram data={histogram.data} /> : null,
      status: histogram.error ?? (histogram.data ? null : "Loading…"),
    },
    {
      key: "ecdf",
      title: `${named} — cumulative share`,
      note: "The share of people at or below each value.",
      chart: histogram.data ? <EcdfChart data={histogram.data} /> : null,
      status: histogram.error ?? (histogram.data ? null : "Loading…"),
    },
    {
      key: "box",
      title: `${named} by ${group || "all rows"} — spread`,
      note: "Median, quartiles and outliers, one box per group.",
      chart: box.data ? <BoxPlot data={box.data} /> : null,
      status: box.error ?? (box.data ? null : "Loading…"),
    },
    {
      key: "scatter",
      title: `${named} against ${against ? labelOf(against) : "another column"}`,
      note: "Two columns plotted together, with the least-squares line.",
      chart: scatter.data ? <ScatterPlot data={scatter.data} /> : null,
      status: scatter.error ?? (scatter.data ? null : "Loading…"),
    },
    {
      key: "corr",
      title: "Correlation matrix",
      note: "Every pair of numeric columns, shaded by strength.",
      // onPick is required, and here there is nothing to pick into — the tile is
      // for exporting, not for driving the scatter on the Figures page.
      chart: correlation.data ? (
        <CorrelationHeatmap data={correlation.data} onPick={() => {}} />
      ) : null,
      status: correlation.error ?? (correlation.data ? null : "Loading…"),
    },
    {
      key: "density",
      title: `${named} by ${group || "all rows"} — distribution shape`,
      note: "Smoothed curves, overlaid so the groups can be compared.",
      chart: density.data ? <DensityPlot data={density.data} /> : null,
      status: density.error ?? (density.data ? null : "Loading…"),
    },
    {
      key: "dose",
      title: "Dose-response across sugar quartiles",
      note: "Mean ALT per quartile with standard errors, and the share above the threshold.",
      chart: dose ? <DoseResponseChart quartiles={dose.quartiles} /> : null,
      status: doseStep.error ?? (dose ? null : "Loading…"),
    },
    {
      key: "forest",
      title: "Model coefficients — with and without BMI",
      note: "Every predictor's standardized β and 95% interval, in both specifications.",
      chart: primary ? (
        <ForestPlot
          models={[
            { label: "Without BMI", model: primary.total_model },
            { label: "With BMI", model: primary.direct_model },
          ]}
        />
      ) : null,
      status: primaryStep.error ?? (primary ? null : "Loading…"),
    },
    {
      key: "qq",
      title: `Normal Q-Q — ${modelLabel}`,
      note: "Whether the model's residuals follow the normal curve its intervals assume.",
      chart: diagnostics.data ? <QQPlot data={diagnostics.data} /> : null,
      status: diagnostics.error ?? (diagnostics.data ? null : "Loading…"),
    },
    {
      key: "resid",
      title: `Residuals against fitted — ${modelLabel}`,
      note: "Whether the model is equally wrong across the range it predicts.",
      chart: diagnostics.data ? <ResidualPlot data={diagnostics.data} /> : null,
      status: diagnostics.error ?? (diagnostics.data ? null : "Loading…"),
    },
  ];

  // The bundle reads the same <svg> elements the tiles rendered, so it needs a
  // handle on each. A Map keyed by the tile's key rather than an array: React
  // may call a ref callback with null on unmount, and the order of those calls
  // is not the render order.
  const plots = useRef(new Map<string, HTMLDivElement>());
  const register = useCallback((key: string, node: HTMLDivElement | null): void => {
    if (node) plots.current.set(key, node);
    else plots.current.delete(key);
  }, []);

  const [format, setFormat] = useState<ExportFormat>("pdf");
  const [progress, setProgress] = useState<string | null>(null);
  const [bundleError, setBundleError] = useState<string | null>(null);

  const ready = useMemo(() => sheets.filter((sheet) => sheet.chart !== null), [sheets]);

  const downloadAll = useCallback(async (): Promise<void> => {
    setBundleError(null);
    const drawn = sheets.filter((sheet) => sheet.chart !== null);
    if (!drawn.length) {
      setBundleError("Nothing has finished loading yet.");
      return;
    }
    const entries: ZipEntry[] = [];
    try {
      for (const [index, sheet] of drawn.entries()) {
        setProgress(`Rendering ${index + 1} of ${drawn.length} — ${sheet.title}`);
        // Yield to the browser between figures. A PNG is a canvas encode and a
        // PDF is a walk over every mark; ten in a row on one task freezes the
        // tab, and on Render's tier the reader is on a slow machine already.
        await new Promise((resolve) => setTimeout(resolve, 0));
        const svg = plots.current.get(sheet.key)?.querySelector("svg");
        if (!svg) continue;
        const blob = await figureBlob(svg as SVGSVGElement, sheet.title, format);
        entries.push({
          name: figureName(sheet.title, format),
          data: new Uint8Array(await blob.arrayBuffer()),
        });
      }
      if (!entries.length) {
        setBundleError("No figures were ready to export.");
        return;
      }
      setProgress("Packing the archive…");
      saveBlob(zipBlob(entries), `figures-${format}.zip`);
      setProgress(`Saved ${entries.length} figures as figures-${format}.zip`);
    } catch (error: unknown) {
      setBundleError(
        error instanceof Error ? error.message : "Could not build the bundle.",
      );
      setProgress(null);
    }
  }, [sheets, format]);

  const [bundling, setBundling] = useState(false);
  const runBundle = useCallback((): void => {
    setBundling(true);
    void downloadAll().finally(() => setBundling(false));
  }, [downloadAll]);

  return (
    <>
      <Crumbs here="Downloads" />
      <Masthead
        eyebrow="Take it with you"
        title="Downloads"
        tagline={
          <>
            Every figure the site draws, ready to save. PDF and SVG come out as real
            vector art — the text is still text and the lines stay sharp at poster size —
            and PNG is there for pasting into a slide. Take one, or take all ten at once.
          </>
        }
        byline="by Anirudh Gupta"
        spec={SPEC}
      />

      {columnsError && <Status message={columnsError} isError />}

      <Module index="01" title="Everything At Once" meta="One archive">
        <p className="text">
          Pick a format and take the lot. Each figure is drawn, exported and packed into a
          single <span className="expr">.zip</span> in the browser — nothing is uploaded and
          nothing is generated on the server.
        </p>

        <div className="bundle">
          <div className="bundle-formats" role="group" aria-label="Bundle format">
            {FORMATS.map((entry) => (
              <button
                key={entry.id}
                type="button"
                className={`bundle-format${format === entry.id ? " is-active" : ""}`}
                aria-pressed={format === entry.id}
                onClick={() => setFormat(entry.id)}
              >
                <span className="bundle-format-label">{entry.label}</span>
                <span className="bundle-format-note">{entry.note}</span>
              </button>
            ))}
          </div>

          <button
            type="button"
            className="bundle-go"
            disabled={bundling || ready.length === 0}
            onClick={runBundle}
          >
            {bundling
              ? "Working…"
              : `Download all ${ready.length} figures · ${format.toUpperCase()} · .zip`}
          </button>

          {progress && (
            <p className="bundle-progress" role="status" aria-live="polite">
              {progress}
            </p>
          )}
          {bundleError && <Status message={bundleError} isError />}
        </div>

        <div className="dl-controls">
          <Picker
            label="Column"
            value={column ?? ""}
            options={columns}
            onChange={(next) => setColumn(next)}
          />
          <Picker
            label="Group"
            value={group}
            options={categorical}
            onChange={setGroup}
            allowNone
            noneLabel="No split"
          />
          <Picker
            label="Against"
            value={against ?? ""}
            options={columns}
            onChange={(next) => setAgainst(next)}
          />
          <Picker
            label="Model"
            value={model}
            options={[...DIAGNOSTIC_MODELS]}
            onChange={setModel}
          />
        </div>
      </Module>

      <Module index="02" title="Every Figure" meta={`${sheets.length} available`}>
        <p className="text">
          What each tile shows is what its file will contain — the same column, the same
          group, the same marks. Change a control above and the downloads change with it.
        </p>
        <div className="dl-grid">
          {sheets.map((sheet) => (
            <DownloadTile key={sheet.key} sheet={sheet} register={register} />
          ))}
        </div>
      </Module>
    </>
  );
}

/** One figure, its caption, and three large buttons. */
function DownloadTile({
  sheet,
  register,
}: {
  sheet: Sheet;
  register: (key: string, node: HTMLDivElement | null) => void;
}): JSX.Element {
  const [busy, setBusy] = useState<ExportFormat | null>(null);
  const [error, setError] = useState<string | null>(null);
  const holder = useRef<HTMLDivElement | null>(null);

  const save = async (format: ExportFormat): Promise<void> => {
    const svg = holder.current?.querySelector("svg");
    if (!svg) {
      setError("This figure has not finished drawing.");
      return;
    }
    setBusy(format);
    setError(null);
    try {
      saveBlob(
        await figureBlob(svg as SVGSVGElement, sheet.title, format),
        figureName(sheet.title, format),
      );
    } catch (problem: unknown) {
      setError(problem instanceof Error ? problem.message : "Could not export this one.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <article className="dl">
      <div
        className="dl-plot"
        ref={(node) => {
          holder.current = node;
          register(sheet.key, node);
        }}
      >
        {sheet.chart ?? <p className="dl-waiting">{sheet.status}</p>}
      </div>

      <div className="dl-meta">
        <h3 className="dl-title">{sheet.title}</h3>
        <p className="dl-note">{sheet.note}</p>
        <p className="dl-file">{slugify(sheet.title)}</p>
      </div>

      <div className="dl-actions">
        {FORMATS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            className="dl-btn"
            disabled={busy !== null || sheet.chart === null}
            onClick={() => void save(entry.id)}
            title={`Download ${sheet.title} as ${entry.label}`}
          >
            <span className="dl-btn-label">
              {busy === entry.id ? "…" : entry.label}
            </span>
            <span className="dl-btn-note">{entry.note}</span>
          </button>
        ))}
      </div>

      {error && <Status message={error} isError />}
    </article>
  );
}
