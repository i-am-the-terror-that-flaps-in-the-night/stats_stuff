// Chart maths: scales, tick selection and number formatting.
//
// WHY THERE IS NO CHARTING LIBRARY HERE
//   The four figures on the Figures page need a linear scale, a tick generator
//   and an SVG path. That is this file, ~120 lines, and it ships as part of a
//   bundle that is already downloaded. The smallest charting library that could
//   draw them costs tens of kilobytes on a service whose whole performance story
//   is "boot fast, stay small" -- and would still need this much glue to match
//   the console's type and colour. Hand-rolled SVG also means the marks obey the
//   same CSS tokens as everything else on the page instead of a second,
//   parallel theme.
//
// Everything here is pure: numbers in, numbers out, no React and no DOM. That is
// what makes it testable and what keeps the chart components down to layout.

/** A mapping from data space to pixel space. */
export interface Scale {
  (value: number): number;
  /** The inverse — pixels back to data. Needed to turn a mouse x into a value. */
  invert(pixel: number): number;
  domain: [number, number];
  range: [number, number];
}

/**
 * A linear scale. A zero-width domain (every value identical, which real columns
 * do produce) would divide by zero, so it degenerates to the middle of the range
 * rather than emitting NaN and blanking the chart.
 */
export function linearScale(domain: [number, number], range: [number, number]): Scale {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0;
  const mid = (r0 + r1) / 2;

  const scale = ((value: number): number =>
    span === 0 ? mid : r0 + ((value - d0) / span) * (r1 - r0)) as Scale;

  scale.invert = (pixel: number): number =>
    r1 === r0 ? d0 : d0 + ((pixel - r0) / (r1 - r0)) * span;
  scale.domain = domain;
  scale.range = range;
  return scale;
}

/**
 * Round a step up to the nearest 1, 2, 5 or 10 × a power of ten.
 *
 * This is what stops an axis reading "0, 3.7143, 7.4286". People read scales by
 * mental arithmetic, and only these steps divide evenly enough to do it at a
 * glance.
 */
function niceStep(rough: number): number {
  const power = Math.pow(10, Math.floor(Math.log10(rough)));
  const normalized = rough / power;
  if (normalized <= 1) return power;
  if (normalized <= 2) return 2 * power;
  if (normalized <= 5) return 5 * power;
  return 10 * power;
}

/**
 * Tick values covering [min, max], spaced on a human-readable step.
 *
 * `count` is a target, not a promise: honouring it exactly is what forces ugly
 * steps. Returns at least the two endpoints so an axis is never bare.
 */
export function ticks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) return [min];
  const step = niceStep((max - min) / Math.max(1, count));
  const first = Math.ceil(min / step) * step;
  const out: number[] = [];
  // Accumulate by multiplication rather than repeated addition: adding 0.1 forty
  // times lands on 4.000000000000001, which then prints as its own tick label.
  for (let i = 0; first + i * step <= max + step * 1e-9; i++) {
    out.push(Number((first + i * step).toPrecision(12)));
  }
  return out.length >= 2 ? out : [min, max];
}

/**
 * Expand a domain outward to the next round number, so the topmost bar or point
 * is not flush against the frame and the axis ends on a label worth reading.
 */
export function niceDomain(min: number, max: number, count = 5): [number, number] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1];
  if (min === max) return min === 0 ? [0, 1] : [Math.min(0, min), Math.max(0, max * 1.1)];
  const step = niceStep((max - min) / Math.max(1, count));
  return [Math.floor(min / step) * step, Math.ceil(max / step) * step];
}

/**
 * Format a number for an axis tick or a tooltip.
 *
 * Charts here span BMI (tens), triglycerides (hundreds) and income ratios
 * (single digits with decimals that matter), so a fixed precision is wrong for
 * at least one of them. Precision is chosen from magnitude, and thousands get a
 * separator because "9254" and "92540" are otherwise hard to tell apart in a
 * column of axis labels.
 */
export function formatTick(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const magnitude = Math.abs(value);
  if (magnitude === 0) return "0";
  if (magnitude >= 1000) return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
  if (magnitude >= 100) return value.toFixed(0);
  if (magnitude >= 10) return value.toFixed(magnitude % 1 === 0 ? 0 : 1);
  if (magnitude >= 1) return value.toFixed(magnitude % 1 === 0 ? 0 : 2);
  return value.toPrecision(2);
}

/** Format a count with thousands separators. */
export function formatCount(value: number): string {
  return value.toLocaleString("en-US");
}

/** Split a CamelCase column name for display: "HDLCholesterol" -> "HDL Cholesterol". */
export function labelOf(column: string): string {
  return column
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2");
}

/** The plot area inside a chart's SVG, after the axis gutters. */
export interface Plot {
  width: number;
  height: number;
  left: number;
  top: number;
  right: number;
  bottom: number;
  innerWidth: number;
  innerHeight: number;
}

export function plotArea(
  width: number,
  height: number,
  margin: { top: number; right: number; bottom: number; left: number },
): Plot {
  return {
    width,
    height,
    left: margin.left,
    top: margin.top,
    right: width - margin.right,
    bottom: height - margin.bottom,
    innerWidth: Math.max(0, width - margin.left - margin.right),
    innerHeight: Math.max(0, height - margin.top - margin.bottom),
  };
}
