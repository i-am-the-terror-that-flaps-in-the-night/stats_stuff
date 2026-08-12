// Tests for the layout decisions in format.ts.
//
// These are the rules that decide whether a label-value pair fits in one grid
// cell or needs its own row, and they are worth testing because getting them
// wrong does not throw -- it produces a page that renders "0.5011" as one digit
// per line and "TrigHDLRatio" broken mid-word, while every request returns 200
// and every backend test passes.
//
// That is exactly what shipped: `isWideValue` only looked at the VALUE, so a
// long label with a short numeric value ("Proportion At Or Above" / 0.5011) was
// classed as narrow, the non-wrapping label consumed the whole 208px cell, and
// the value was left with a couple of characters to render in.

import { describe, expect, it } from "vitest";
import {
  isProse,
  isWidePair,
  isWideValue,
  MAX_INLINE_LABEL,
  MAX_INLINE_TOKEN,
  prettify,
} from "./format";

describe("prettify", () => {
  it("turns engine snake_case keys into readable labels", () => {
    expect(prettify("proportion_at_or_above")).toBe("proportion at or above");
    expect(prettify("n")).toBe("n");
  });
});

describe("isWideValue", () => {
  it("treats lists of more than two items as wide", () => {
    expect(isWideValue(["a", "b"])).toBe(false);
    expect(isWideValue(["a", "b", "c"])).toBe(true);
  });

  it("treats long strings as wide", () => {
    expect(isWideValue("mg/dL")).toBe(false);
    expect(isWideValue("a string comfortably past the limit")).toBe(true);
  });

  it("leaves plain numbers narrow", () => {
    expect(isWideValue(0.5011)).toBe(false);
    expect(isWideValue(699)).toBe(false);
  });
});

describe("isWidePair", () => {
  // The regression case. A short number under a long label was the combination
  // that rendered vertically.
  it("gives a long label its own row even when the value is a short number", () => {
    expect(isWidePair("proportion_at_or_above", 0.5011)).toBe(true);
    expect(isWidePair("standardized_beta", 0.138)).toBe(true);
  });

  it("keeps a short label and a short value in one cell", () => {
    expect(isWidePair("mean", 16.04)).toBe(false);
    expect(isWidePair("n", 699)).toBe(false);
    expect(isWidePair("median", 1.574)).toBe(false);
  });

  // The other half: a value that is one unbreakable token. "TrigHDLRatio" has
  // no space or hyphen, so it cannot wrap politely -- it fits or it is chopped.
  it("gives an unbreakable long token its own row", () => {
    expect(isWidePair("column", "TrigHDLRatio")).toBe(true);
    expect(isWidePair("column", "HDLCholesterol")).toBe(true);
  });

  it("keeps a short column name inline", () => {
    expect(isWidePair("column", "ALT")).toBe(false);
    expect(isWidePair("column", "BMI")).toBe(false);
    expect(isWidePair("layer", "descriptive")).toBe(false);
  });

  it("measures the longest token, not the whole string", () => {
    // Three short words wrap at the spaces and fit fine; the same character
    // count in one token does not.
    expect(isWidePair("unit", "at or above")).toBe(false);
    expect(isWidePair("unit", "atorabovexxx")).toBe(true);
  });

  it("still routes lists and long strings through, as before", () => {
    expect(isWidePair("predictors", ["Sugar10g", "Age", "Male", "BMI"])).toBe(true);
    expect(isWidePair("estimator", "WLS with cluster-robust standard errors")).toBe(true);
  });

  // Every key the engine actually emits into a stat cell should render sanely.
  // This is the check that would have caught the original bug across the board
  // rather than one column at a time.
  it("classifies every real engine stat key without leaving a squeezed cell", () => {
    const realPairs: [string, number | string][] = [
      ["n", 699],
      ["mean", 16.04],
      ["median", 13],
      ["std", 11.42],
      ["variance", 130.4],
      ["min", 2],
      ["max", 152],
      ["column", "TrigHDLRatio"],
      ["layer", "descriptive"],
      ["at_or_above", 350],
      ["below", 349],
      ["proportion_at_or_above", 0.5011],
      ["cutoff", 6.5],
      ["unit", "%"],
      ["flagged", 86],
      ["skewness", 3.42],
      ["kurtosis", 21.1],
      ["standardized_beta", 0.138],
      ["p_value", 0.0048],
      ["r_squared", 0.1539],
    ];

    for (const [key, value] of realPairs) {
      const label = prettify(key).length;
      const token =
        typeof value === "string"
          ? Math.max(...value.split(/[\s_-]+/).map((t) => t.length))
          : 0;
      // Anything that would be squeezed must be classed wide. The thresholds
      // are imported rather than restated, so tuning one of them cannot leave
      // this test asserting the old rule.
      if (label > MAX_INLINE_LABEL || token > MAX_INLINE_TOKEN) {
        expect(isWidePair(key, value), `${key} should be wide`).toBe(true);
      }
    }
  });
});

describe("isProse", () => {
  it("routes the engine's explanatory sentences to their own note block", () => {
    expect(isProse("note", "The median is a property of this sample, not a clinical threshold.")).toBe(
      true,
    );
    expect(isProse("mean", 16.04)).toBe(false);
  });
});
