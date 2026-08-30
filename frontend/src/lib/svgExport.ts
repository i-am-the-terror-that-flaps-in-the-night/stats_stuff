// Downloading a figure — as PNG, as a real vector PDF, or as SVG.
//
// WHY THERE IS NO EXPORT LIBRARY HERE
//   Same argument as lib/scales.ts. The charts on this site are a small, known
//   subset of SVG — rect, line, circle, path, polyline, text, and groups with a
//   transform — drawn by components in this repo. A general SVG-to-PDF library
//   has to handle filters, gradients, clip paths, embedded fonts and foreign
//   objects, none of which appear here, and costs tens of kilobytes on a service
//   whose performance story is "boot fast, stay small". Writing the subset out
//   as PDF operators is about two hundred lines, and it is the only way to get a
//   PDF whose text is still text.
//
// WHY VECTOR AND NOT A SCREENSHOT
//   The intended destination is a printed poster. A raster export is fixed at
//   whatever pixel size it was taken at and goes soft the moment it is enlarged;
//   a vector PDF is resolution-independent, so the same file prints correctly at
//   postcard size and at A0. PNG is offered as well because it is what pastes
//   into a slide deck or a document without any conversion step.
//
// HOW THE STYLING SURVIVES
//   The marks are styled by CSS class (.fig-bar, .fig-grid, …) against the
//   console's design tokens, so an <svg> lifted out of the page carries no
//   colour at all on its own. Every path below therefore reads the *computed*
//   style off the live element and bakes it in: as presentation attributes for
//   PNG and SVG, as fill/stroke operators for PDF. Nothing here re-declares a
//   colour, so a change to a token in styles.css moves the downloads with it.

/** The three things a reader can ask for. */
export type ExportFormat = "png" | "pdf" | "svg";

/** Internal coordinate space is the viewBox; PDF uses 1 unit = 1 point. */
interface Box {
  width: number;
  height: number;
}

/** The properties that decide how a mark looks. Copied onto standalone SVG. */
const PAINT_PROPS = [
  "fill",
  "fill-opacity",
  "stroke",
  "stroke-width",
  "stroke-opacity",
  "stroke-dasharray",
  "stroke-linecap",
  "stroke-linejoin",
  "opacity",
  "font-family",
  "font-size",
  "font-weight",
  "letter-spacing",
  "text-anchor",
  "text-transform",
  "paint-order",
] as const;

// ---------------------------------------------------------------------------
// SHARED HELPERS
// ---------------------------------------------------------------------------

/** The chart's own coordinate space, from the viewBox rather than the layout. */
function boxOf(svg: SVGSVGElement): Box {
  const view = svg.viewBox.baseVal;
  if (view && view.width > 0 && view.height > 0) {
    return { width: view.width, height: view.height };
  }
  const rect = svg.getBoundingClientRect();
  return { width: rect.width || 720, height: rect.height || 340 };
}

/** `rgb(31, 79, 255)` / `rgba(…)` / `none` → [r, g, b, a] in 0–1, or null. */
function parseColor(value: string): [number, number, number, number] | null {
  if (!value || value === "none" || value === "transparent") return null;
  const parts = value.match(/[\d.]+/g);
  if (!parts || parts.length < 3) return null;
  const [r, g, b] = parts.map(Number);
  const a = parts.length > 3 ? Number(parts[3]) : 1;
  if (r === undefined || g === undefined || b === undefined) return null;
  return [r / 255, g / 255, b / 255, a];
}

/** Trim a number for a file format that will be read by a machine. */
function n(value: number): string {
  return Number.isFinite(value) ? String(Math.round(value * 1000) / 1000) : "0";
}

/** `text-transform: uppercase` is applied at render time, not in the DOM. */
function applyTransform(text: string, style: CSSStyleDeclaration): string {
  const rule = style.getPropertyValue("text-transform");
  if (rule === "uppercase") return text.toUpperCase();
  if (rule === "lowercase") return text.toLowerCase();
  return text;
}

/** Skip anything invisible, plus the nodes that carry no ink. */
function isDrawn(el: Element, style: CSSStyleDeclaration): boolean {
  if (style.display === "none" || style.visibility === "hidden") return false;
  return !["title", "desc", "defs", "metadata"].includes(el.tagName.toLowerCase());
}

/** Ask the browser to save a blob under a name. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoked on the next tick rather than immediately: Safari has not finished
  // reading the object URL when click() returns, and a revoked URL saves a
  // zero-byte file.
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** A filename stem from a figure title: "ALT by sex" -> "alt-by-sex". */
export function slugify(title: string): string {
  return (
    title
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || "figure"
  );
}

// ---------------------------------------------------------------------------
// SVG — the same drawing, made self-contained
// ---------------------------------------------------------------------------

/**
 * A deep clone with every computed style baked in as an attribute.
 *
 * Walks the live tree and the clone in lockstep, because the computed style is
 * only available on the element that is actually in the document — the clone is
 * detached and would report nothing but defaults.
 */
function styledClone(svg: SVGSVGElement): SVGSVGElement {
  const box = boxOf(svg);
  const clone = svg.cloneNode(true) as SVGSVGElement;

  const live = [svg, ...svg.querySelectorAll("*")];
  const copies = [clone, ...clone.querySelectorAll("*")];
  live.forEach((element, index) => {
    const copy = copies[index];
    if (!copy) return;
    const style = window.getComputedStyle(element);
    for (const property of PAINT_PROPS) {
      const value = style.getPropertyValue(property);
      if (value && value !== "normal" && value !== "none") {
        copy.setAttribute(property, value);
      }
    }
    // `fill: none` is meaningful — it is what keeps a line chart's path hollow —
    // so it is set explicitly rather than skipped with the other "none"s above.
    if (style.getPropertyValue("fill") === "none") copy.setAttribute("fill", "none");
    if (copy instanceof SVGElement && copy.tagName.toLowerCase() === "text") {
      copy.textContent = applyTransform(copy.textContent ?? "", style);
      copy.removeAttribute("text-transform");
    }
  });

  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(box.width));
  clone.setAttribute("height", String(box.height));
  clone.removeAttribute("class");

  // An opaque page. On screen the figure sits on the console's surface colour;
  // exported on its own it would have a transparent background, which reads as
  // black in most PDF viewers and in any dark-themed image preview.
  const background = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  background.setAttribute("x", "0");
  background.setAttribute("y", "0");
  background.setAttribute("width", String(box.width));
  background.setAttribute("height", String(box.height));
  background.setAttribute("fill", surfaceColor());
  clone.insertBefore(background, clone.firstChild);
  return clone;
}

/** The console's surface token, resolved to a real colour. */
function surfaceColor(): string {
  const value = window
    .getComputedStyle(document.documentElement)
    .getPropertyValue("--surface")
    .trim();
  return value || "#ffffff";
}

export function toSvgBlob(svg: SVGSVGElement): Blob {
  const markup = new XMLSerializer().serializeToString(styledClone(svg));
  return new Blob([`<?xml version="1.0" encoding="UTF-8"?>\n${markup}`], {
    type: "image/svg+xml;charset=utf-8",
  });
}

// ---------------------------------------------------------------------------
// PNG — the same drawing, rasterized
// ---------------------------------------------------------------------------

/**
 * Rasterize at `scale`× the chart's own coordinate space.
 *
 * 3× is the default because these charts are authored around 720 units wide, so
 * the export lands at 2160px — sharp on a retina screen, and about 360 DPI
 * across a six-inch column in print, which is past the point anyone can see the
 * pixels. It is still a raster: the PDF is the one to enlarge.
 */
export async function toPngBlob(svg: SVGSVGElement, scale = 3): Promise<Blob> {
  const box = boxOf(svg);
  const markup = new XMLSerializer().serializeToString(styledClone(svg));
  // A data URL rather than an object URL: an SVG loaded from a blob taints the
  // canvas in some browsers, and a tainted canvas cannot be read back.
  const source = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`;

  const image = new Image();
  image.decoding = "sync";
  await new Promise<void>((resolve, reject) => {
    image.onload = () => resolve();
    image.onerror = () => reject(new Error("Could not rasterize the figure."));
    image.src = source;
  });

  const canvas = document.createElement("canvas");
  canvas.width = Math.round(box.width * scale);
  canvas.height = Math.round(box.height * scale);
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Canvas is unavailable in this browser.");
  context.fillStyle = surfaceColor();
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);

  return await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("Could not encode the PNG."))),
      "image/png",
    );
  });
}

// ---------------------------------------------------------------------------
// PDF — the same drawing, as vector operators
// ---------------------------------------------------------------------------

/**
 * What a page is being built into.
 *
 * `alphas` and `fonts` are resource dictionaries built as they are needed: PDF
 * cannot express constant transparency inline (it takes an ExtGState) and can
 * only name a font that the page's resources declare, so both are interned here
 * and written into the page object at the end.
 */
interface Content {
  ops: string[];
  alphas: Map<string, string>;
  fonts: Map<string, string>;
}

/** Intern an /ExtGState for a fill/stroke alpha pair, returning its name. */
function alphaState(content: Content, fill: number, stroke: number): string | null {
  if (fill >= 1 && stroke >= 1) return null;
  const key = `${n(fill)} ${n(stroke)}`;
  let name = content.alphas.get(key);
  if (!name) {
    name = `GS${content.alphas.size}`;
    content.alphas.set(key, name);
  }
  return name;
}

/** Intern one of the base-14 fonts, returning its resource name. */
function fontResource(content: Content, base: string): string {
  let name = content.fonts.get(base);
  if (!name) {
    name = `F${content.fonts.size}`;
    content.fonts.set(base, name);
  }
  return name;
}

/**
 * A base-14 font for a CSS font stack.
 *
 * The site's stack is system-ui, which is Helvetica on macOS and a metrically
 * compatible Arial elsewhere — so Helvetica is not an approximation of the
 * screen so much as the same shapes under the name PDF already knows. Base-14
 * means nothing is embedded, which keeps the file a few kilobytes.
 */
function baseFont(style: CSSStyleDeclaration): string {
  const family = style.getPropertyValue("font-family").toLowerCase();
  const bold = Number(style.getPropertyValue("font-weight")) >= 600;
  if (family.includes("mono") || family.includes("courier")) {
    return bold ? "Courier-Bold" : "Courier";
  }
  return bold ? "Helvetica-Bold" : "Helvetica";
}

/**
 * Width of a run of text in the font PDF will actually use.
 *
 * Measured on a canvas rather than from an embedded metrics table: the browser
 * has the real font, and asking it for the width is both exact and free. This
 * is what makes a centred or right-anchored label land where it does on screen
 * instead of drifting by the difference between two fonts' advance widths.
 */
let scratch: CanvasRenderingContext2D | null | undefined;

/** The measuring canvas, made on first use. Deliberately not built at module
 *  scope: this file is imported by a test runner with no DOM, and touching
 *  `document` while the module evaluates would take the whole module down. */
function measuringContext(): CanvasRenderingContext2D | null {
  if (scratch === undefined) {
    scratch =
      typeof document === "undefined"
        ? null
        : document.createElement("canvas").getContext("2d");
  }
  return scratch;
}

function textWidth(text: string, size: number, base: string, spacing: number): number {
  const context = measuringContext();
  // A crude fallback rather than a throw: a label a few points off is a figure
  // that still reads, and half the em size is close for both base fonts.
  if (!context) return text.length * size * 0.5;
  const family = base.startsWith("Courier") ? "Courier, monospace" : "Helvetica, Arial, sans-serif";
  context.font = `${base.endsWith("Bold") ? "bold " : ""}${size}px ${family}`;
  return context.measureText(text).width + spacing * text.length;
}

/** Escape a string for a PDF literal, and drop what WinAnsi cannot say. */
export function pdfString(text: string): string {
  const swaps: Record<string, string> = {
    // WinAnsi keeps the two dashes in separate slots: 0x97 is the em dash the
    // chart titles use, 0x96 the en dash the numeric ranges use.
    "—": "\\227",
    "–": "\\226",
    "−": "-",
    "≤": "<=",
    "≥": ">=",
    "≈": "~=",
    "→": "->",
    "×": "\\327",
    "·": "\\267",
    "…": "...",
    "“": '"',
    "”": '"',
    "’": "'",
    // Characters WinAnsi does have, and which the axis labels use constantly:
    // every error bar is written "± 1 SE" and every rate is per m². Left out of
    // this table they fell through to "?" — the fallback is for glyphs the
    // encoding genuinely lacks, and these are not those.
    "±": "\\261",
    "²": "\\262",
    "³": "\\263",
    "°": "\\260",
    "µ": "\\265",
    "μ": "\\265",
    // Greek, which WinAnsi genuinely lacks. Spelled out rather than dropped: a
    // legend reading "Standardized beta" is worth more to a reader holding the
    // printout than one reading "Standardized ?". The base-14 Symbol font could
    // draw these properly, but only by switching fonts mid-line, which means
    // measuring each run to place the next — a real amount of machinery for
    // four characters.
    "α": "alpha",
    "β": "beta",
    "η": "eta",
    "σ": "sigma",
    "ρ": "rho",
    "χ": "chi",
    "δ": "delta",
    // The capitals are not decoration. Axis captions are uppercased by CSS and
    // that transform is applied before this runs (see applyTransform), so
    // "Standardized β" arrives here as "STANDARDIZED Β" — a different code
    // point, which fell straight through to "?" while the lowercase entry above
    // sat unused. Whatever is added to this table needs both cases.
    "Α": "ALPHA",
    "Β": "BETA",
    "Η": "ETA",
    "Σ": "SIGMA",
    "Ρ": "RHO",
    "Χ": "CHI",
    "Δ": "DELTA",
    "Μ": "MU",
  };
  let out = "";
  for (const character of text) {
    if (swaps[character] !== undefined) out += swaps[character];
    else if (character === "\\") out += "\\\\";
    else if (character === "(") out += "\\(";
    else if (character === ")") out += "\\)";
    else if (character.charCodeAt(0) < 128) out += character;
    else out += "?";
  }
  return out;
}

/** Emit the fill/stroke setup for one element, and return the painting op. */
function paintFor(content: Content, style: CSSStyleDeclaration, canFill: boolean): string | null {
  const opacity = Number(style.getPropertyValue("opacity") || 1);
  const fill = canFill ? parseColor(style.getPropertyValue("fill")) : null;
  const stroke = parseColor(style.getPropertyValue("stroke"));
  const strokeWidth = parseFloat(style.getPropertyValue("stroke-width") || "0");

  const fillAlpha = fill ? fill[3] * Number(style.getPropertyValue("fill-opacity") || 1) * opacity : 0;
  const strokeAlpha = stroke
    ? stroke[3] * Number(style.getPropertyValue("stroke-opacity") || 1) * opacity
    : 0;
  const paintsFill = fill !== null && fillAlpha > 0.001;
  const paintsStroke = stroke !== null && strokeAlpha > 0.001 && strokeWidth > 0;
  if (!paintsFill && !paintsStroke) return null;

  const gs = alphaState(content, paintsFill ? fillAlpha : 1, paintsStroke ? strokeAlpha : 1);
  if (gs) content.ops.push(`/${gs} gs`);
  if (paintsFill && fill) content.ops.push(`${n(fill[0])} ${n(fill[1])} ${n(fill[2])} rg`);
  if (paintsStroke && stroke) {
    content.ops.push(`${n(stroke[0])} ${n(stroke[1])} ${n(stroke[2])} RG`);
    content.ops.push(`${n(strokeWidth)} w`);
    const caps = ["butt", "round", "square"].indexOf(style.getPropertyValue("stroke-linecap"));
    content.ops.push(`${caps < 0 ? 0 : caps} J`);
    const dashes = (style.getPropertyValue("stroke-dasharray").match(/[\d.]+/g) ?? []).map(Number);
    content.ops.push(dashes.length ? `[${dashes.map(n).join(" ")}] 0 d` : "[] 0 d");
  }
  if (paintsFill && paintsStroke) return "B";
  return paintsFill ? "f" : "S";
}

/** A circle as four Béziers. 0.5523 is the standard circle-to-cubic constant. */
function circlePath(cx: number, cy: number, rx: number, ry: number): string {
  const kx = rx * 0.5523;
  const ky = ry * 0.5523;
  return [
    `${n(cx + rx)} ${n(cy)} m`,
    `${n(cx + rx)} ${n(cy + ky)} ${n(cx + kx)} ${n(cy + ry)} ${n(cx)} ${n(cy + ry)} c`,
    `${n(cx - kx)} ${n(cy + ry)} ${n(cx - rx)} ${n(cy + ky)} ${n(cx - rx)} ${n(cy)} c`,
    `${n(cx - rx)} ${n(cy - ky)} ${n(cx - kx)} ${n(cy - ry)} ${n(cx)} ${n(cy - ry)} c`,
    `${n(cx + kx)} ${n(cy - ry)} ${n(cx + rx)} ${n(cy - ky)} ${n(cx + rx)} ${n(cy)} c`,
  ].join(" ");
}

/**
 * An SVG path `d` as PDF path operators.
 *
 * Handles the commands these charts emit — move, line, horizontal, vertical,
 * cubic and quadratic curves, and close. Arcs are not produced by any component
 * here and are skipped rather than approximated badly; if one ever appears the
 * segment is dropped, not mis-drawn.
 */
export function convertPath(d: string): string {
  const tokens = d.match(/[MmLlHhVvCcSsQqTtZz]|-?[\d.]+(?:e-?\d+)?/g) ?? [];
  const out: string[] = [];
  let index = 0;
  let x = 0;
  let y = 0;
  let startX = 0;
  let startY = 0;
  let previousControl: [number, number] | null = null;
  let command = "";

  const next = (): number => Number(tokens[index++] ?? 0);

  while (index < tokens.length) {
    const token = tokens[index];
    if (token !== undefined && /[MmLlHhVvCcSsQqTtZz]/.test(token)) {
      command = token;
      index++;
    }
    const relative = command === command.toLowerCase();
    const upper = command.toUpperCase();

    if (upper === "Z") {
      out.push("h");
      x = startX;
      y = startY;
      previousControl = null;
      continue;
    }
    if (upper === "M" || upper === "L") {
      const nx = next() + (relative ? x : 0);
      const ny = next() + (relative ? y : 0);
      out.push(`${n(nx)} ${n(ny)} ${upper === "M" ? "m" : "l"}`);
      if (upper === "M") {
        startX = nx;
        startY = ny;
        // A second coordinate pair after M is an implicit lineto, which is what
        // the sequence-without-a-letter form below falls through to.
        command = relative ? "l" : "L";
      }
      x = nx;
      y = ny;
      previousControl = null;
      continue;
    }
    if (upper === "H" || upper === "V") {
      const value = next();
      if (upper === "H") x = relative ? x + value : value;
      else y = relative ? y + value : value;
      out.push(`${n(x)} ${n(y)} l`);
      previousControl = null;
      continue;
    }
    if (upper === "C" || upper === "S") {
      let c1x: number;
      let c1y: number;
      if (upper === "C") {
        c1x = next() + (relative ? x : 0);
        c1y = next() + (relative ? y : 0);
      } else {
        // A smooth cubic reflects the previous control point through the
        // current point; with no previous curve the control point is the point.
        c1x = previousControl ? 2 * x - previousControl[0] : x;
        c1y = previousControl ? 2 * y - previousControl[1] : y;
      }
      const c2x = next() + (relative ? x : 0);
      const c2y = next() + (relative ? y : 0);
      const nx = next() + (relative ? x : 0);
      const ny = next() + (relative ? y : 0);
      out.push(`${n(c1x)} ${n(c1y)} ${n(c2x)} ${n(c2y)} ${n(nx)} ${n(ny)} c`);
      previousControl = [c2x, c2y];
      x = nx;
      y = ny;
      continue;
    }
    if (upper === "Q" || upper === "T") {
      let qx: number;
      let qy: number;
      if (upper === "Q") {
        qx = next() + (relative ? x : 0);
        qy = next() + (relative ? y : 0);
      } else {
        qx = previousControl ? 2 * x - previousControl[0] : x;
        qy = previousControl ? 2 * y - previousControl[1] : y;
      }
      const nx = next() + (relative ? x : 0);
      const ny = next() + (relative ? y : 0);
      // PDF has no quadratic operator; the exact cubic equivalent raises the
      // two control points to thirds along the legs.
      out.push(
        `${n(x + (2 / 3) * (qx - x))} ${n(y + (2 / 3) * (qy - y))} ` +
          `${n(nx + (2 / 3) * (qx - nx))} ${n(ny + (2 / 3) * (qy - ny))} ${n(nx)} ${n(ny)} c`,
      );
      previousControl = [qx, qy];
      x = nx;
      y = ny;
      continue;
    }
    // Anything unhandled (an arc) — consume one number so this cannot spin.
    index++;
  }
  return out.join(" ");
}

/** `points="1,2 3,4"` as PDF path operators. */
export function convertPoints(points: string, close: boolean): string {
  const numbers = (points.match(/-?[\d.]+/g) ?? []).map(Number);
  const out: string[] = [];
  for (let i = 0; i + 1 < numbers.length; i += 2) {
    out.push(`${n(numbers[i] ?? 0)} ${n(numbers[i + 1] ?? 0)} ${i === 0 ? "m" : "l"}`);
  }
  if (close && out.length) out.push("h");
  return out.join(" ");
}

/** Draw one element into the content stream, under its own transform. */
function drawElement(el: SVGGraphicsElement, content: Content, toRoot: DOMMatrix): void {
  const style = window.getComputedStyle(el);
  if (!isDrawn(el, style)) return;

  const tag = el.tagName.toLowerCase();
  let geometry = "";
  let canFill = true;

  if (tag === "rect") {
    const r = el as unknown as SVGRectElement;
    geometry = `${n(r.x.baseVal.value)} ${n(r.y.baseVal.value)} ${n(r.width.baseVal.value)} ${n(r.height.baseVal.value)} re`;
  } else if (tag === "line") {
    const l = el as unknown as SVGLineElement;
    geometry = `${n(l.x1.baseVal.value)} ${n(l.y1.baseVal.value)} m ${n(l.x2.baseVal.value)} ${n(l.y2.baseVal.value)} l`;
    canFill = false;
  } else if (tag === "circle") {
    const c = el as unknown as SVGCircleElement;
    const r = c.r.baseVal.value;
    geometry = circlePath(c.cx.baseVal.value, c.cy.baseVal.value, r, r);
  } else if (tag === "ellipse") {
    const e = el as unknown as SVGEllipseElement;
    geometry = circlePath(e.cx.baseVal.value, e.cy.baseVal.value, e.rx.baseVal.value, e.ry.baseVal.value);
  } else if (tag === "path") {
    geometry = convertPath(el.getAttribute("d") ?? "");
  } else if (tag === "polyline" || tag === "polygon") {
    geometry = convertPoints(el.getAttribute("points") ?? "", tag === "polygon");
  } else if (tag === "text") {
    drawText(el, content, toRoot, style);
    return;
  } else {
    return;
  }

  if (!geometry) return;
  const op = paintFor(content, style, canFill);
  if (!op) return;
  content.ops.push("q");
  content.ops.push(matrixOps(toRoot));
  content.ops.push(geometry);
  content.ops.push(op);
  content.ops.push("Q");
}

/** One text run, anchored the way SVG anchors it. */
function drawText(
  el: SVGGraphicsElement,
  content: Content,
  toRoot: DOMMatrix,
  style: CSSStyleDeclaration,
): void {
  const text = applyTransform((el.textContent ?? "").trim(), style);
  if (!text) return;

  const fill = parseColor(style.getPropertyValue("fill"));
  if (!fill) return;
  const opacity = Number(style.getPropertyValue("opacity") || 1) * fill[3];
  if (opacity <= 0.001) return;

  const size = parseFloat(style.getPropertyValue("font-size") || "10");
  const spacingRule = style.getPropertyValue("letter-spacing");
  const spacing = spacingRule.endsWith("px") ? parseFloat(spacingRule) : 0;
  const base = baseFont(style);
  const font = fontResource(content, base);

  // SVG places text by its anchor; PDF always draws rightward from the origin,
  // so the anchor is resolved here into a plain left-edge x.
  const anchor = style.getPropertyValue("text-anchor");
  const width = textWidth(text, size, base, spacing);
  const x = Number(el.getAttribute("x") ?? 0);
  const y = Number(el.getAttribute("y") ?? 0);
  const left = anchor === "middle" ? x - width / 2 : anchor === "end" ? x - width : x;

  const gs = alphaState(content, opacity, 1);
  content.ops.push("q");
  content.ops.push(matrixOps(toRoot));
  if (gs) content.ops.push(`/${gs} gs`);
  content.ops.push(`${n(fill[0])} ${n(fill[1])} ${n(fill[2])} rg`);
  content.ops.push("BT");
  content.ops.push(`/${font} ${n(size)} Tf`);
  if (spacing) content.ops.push(`${n(spacing)} Tc`);
  // The page is flipped once, globally, to put SVG's y-down space the right way
  // up. Glyphs would come out mirrored under that flip, so the text matrix
  // flips back — which also negates any rotation, exactly as it should, since a
  // clockwise rotation in y-down space is anticlockwise in y-up space.
  content.ops.push(`1 0 0 -1 ${n(left)} ${n(y)} Tm`);
  content.ops.push(`(${pdfString(text)}) Tj`);
  content.ops.push("ET");
  content.ops.push("Q");
}

/** A DOMMatrix as a PDF `cm` operator. */
function matrixOps(m: DOMMatrix): string {
  return `${n(m.a)} ${n(m.b)} ${n(m.c)} ${n(m.d)} ${n(m.e)} ${n(m.f)} cm`;
}

/**
 * Build the whole PDF.
 *
 * One page, sized to the chart's own coordinate space at 1 unit = 1 point. That
 * makes a 720×340 chart a 10 × 4.7 inch page, which is a sensible default — and
 * because everything on it is vector, the size it was authored at places no
 * limit on the size it can be printed at.
 */
export function toPdfBlob(svg: SVGSVGElement, title: string): Blob {
  const box = boxOf(svg);
  const content: Content = { ops: [], alphas: new Map(), fonts: new Map() };

  // Paint the page, then flip into SVG's y-down space for everything after.
  content.ops.push("q");
  const surface = parseColor(surfaceColor()) ?? [1, 1, 1, 1];
  content.ops.push(`${n(surface[0])} ${n(surface[1])} ${n(surface[2])} rg`);
  content.ops.push(`0 0 ${n(box.width)} ${n(box.height)} re f`);
  content.ops.push("Q");
  content.ops.push(`1 0 0 -1 0 ${n(box.height)} cm`);

  // Each element is placed by its own matrix relative to the root, rather than
  // by walking transforms down the tree: the browser has already resolved every
  // nested translate/rotate, and asking it is both shorter and exact.
  const rootScreen = svg.getScreenCTM();
  for (const element of svg.querySelectorAll("*")) {
    // Not everything under an <svg> is drawable. <title> is the standard way to
    // give a shape a native tooltip and appears inside the marks it describes;
    // <desc>, <defs>, <style> and <metadata> are the same kind of thing. None of
    // them is an SVGGraphicsElement, so none of them has getScreenCTM, and
    // calling it threw a TypeError that aborted the whole export -- a figure
    // whose only fault was being accessible would not save as a PDF.
    if (!(element instanceof SVGGraphicsElement)) continue;
    const own = element.getScreenCTM();
    const toRoot = rootScreen && own ? rootScreen.inverse().multiply(own) : new DOMMatrix();
    drawElement(element, content, toRoot);
  }

  return new Blob(
    [
      assemblePdf({
        stream: content.ops.join("\n"),
        width: box.width,
        height: box.height,
        fonts: [...content.fonts.keys()],
        alphas: [...content.alphas.entries()],
        title,
      }),
    ],
    { type: "application/pdf" },
  );
}

/**
 * The PDF file itself: objects, the cross-reference table, and the trailer.
 *
 * Split out from the drawing walk above because this half is pure — strings in,
 * one string out — and because it is the half where a mistake is invisible
 * until a reader refuses the file. The xref table is a list of BYTE offsets to
 * each object, so every chunk is measured after encoding rather than by
 * `.length`: a single non-ASCII character in a title would otherwise shift
 * every offset after it by one and corrupt the file.
 */
export function assemblePdf(options: {
  stream: string;
  width: number;
  height: number;
  /** Base-14 font names, in the order their resource names were handed out. */
  fonts: string[];
  /** [`${ca} ${CA}`, resourceName] for each transparency state used. */
  alphas: [string, string][];
  title: string;
}): string {
  const { stream, width, height, fonts, alphas, title } = options;
  const encoder = new TextEncoder();

  const fontResources = fonts.map((_, i) => `/F${i} ${5 + i} 0 R`).join(" ");
  const alphaResources = alphas
    .map(([key, name]) => {
      const [ca, CA] = key.split(" ");
      return `/${name} <</Type/ExtGState/ca ${ca}/CA ${CA}>>`;
    })
    .join(" ");

  // Object 1 is the catalog, 2 the page tree, 3 the page, 4 its content
  // stream, and 5 onward one per font — the numbering the page dictionary above
  // refers to, so the two must stay in step.
  const objects: string[] = [
    "<</Type/Catalog/Pages 2 0 R>>",
    "<</Type/Pages/Kids[3 0 R]/Count 1>>",
    `<</Type/Page/Parent 2 0 R/MediaBox[0 0 ${n(width)} ${n(height)}]` +
      `/Resources<</Font<<${fontResources}>>/ExtGState<<${alphaResources}>>>>` +
      "/Contents 4 0 R>>",
    `<</Length ${encoder.encode(stream).length}>>\nstream\n${stream}\nendstream`,
    ...fonts.map(
      (base) => `<</Type/Font/Subtype/Type1/BaseFont/${base}/Encoding/WinAnsiEncoding>>`,
    ),
  ];

  const header = "%PDF-1.4\n";
  const chunks: string[] = [header];
  const offsets: number[] = [];
  let cursor = encoder.encode(header).length;
  objects.forEach((body, index) => {
    const text = `${index + 1} 0 obj\n${body}\nendobj\n`;
    offsets.push(cursor);
    cursor += encoder.encode(text).length;
    chunks.push(text);
  });

  const rows = offsets.map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("");
  chunks.push(
    `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${rows}` +
      `trailer\n<</Size ${objects.length + 1}/Root 1 0 R` +
      `/Info<</Title (${pdfString(title)})/Producer (stats-and-more)>>>>\n` +
      `startxref\n${cursor}\n%%EOF\n`,
  );
  return chunks.join("");
}

// ---------------------------------------------------------------------------
// THE ONE ENTRY POINT
// ---------------------------------------------------------------------------

/** Export one chart and hand it to the browser's downloader. */
export async function downloadFigure(
  svg: SVGSVGElement,
  title: string,
  format: ExportFormat,
): Promise<void> {
  saveBlob(await figureBlob(svg, title, format), figureName(title, format));
}

/**
 * The same three exporters behind one call, returning the blob instead of
 * saving it — which is what the bundle on the Downloads page needs, since it
 * collects ten of these before anything reaches the disk.
 */
export async function figureBlob(
  svg: SVGSVGElement,
  title: string,
  format: ExportFormat,
): Promise<Blob> {
  if (format === "svg") return toSvgBlob(svg);
  if (format === "pdf") return toPdfBlob(svg, title);
  return toPngBlob(svg);
}

/** The filename a figure downloads under, in one place so the single-file and
 *  bundled paths cannot drift apart. */
export function figureName(title: string, format: ExportFormat): string {
  return `${slugify(title)}.${format}`;
}
