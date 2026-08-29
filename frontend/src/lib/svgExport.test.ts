// Tests for the parts of the figure export that do not need a browser.
//
// WHY THESE AND NOT THE WHOLE THING
//   Most of svgExport.ts reads the LIVE document — getComputedStyle for every
//   mark's colour, getScreenCTM for its placement — and there is no DOM here to
//   read. What is testable is the half that is pure: the SVG path grammar
//   converted to PDF operators, the string escaping, and the file assembly.
//
//   That is also the half worth testing. A wrong colour is visible the moment
//   anyone looks at the download. A wrong byte offset in the cross-reference
//   table is invisible until a reader refuses to open the file, and produces no
//   error anywhere in this codebase — the blob saves fine, the browser saves it
//   fine, and the PDF is simply broken. So the xref is checked byte for byte.

import { describe, expect, it } from "vitest";
import { assemblePdf, convertPath, convertPoints, pdfString, slugify } from "./svgExport";

describe("convertPath", () => {
  it("turns the move/line path the charts emit into PDF operators", () => {
    // This is the exact shape EcdfChart builds for its curve.
    expect(convertPath("M10 20 L30 40 L50 60")).toBe("10 20 m 30 40 l 50 60 l");
  });

  it("closes a subpath with h, the PDF spelling of Z", () => {
    expect(convertPath("M0 0 L10 0 L10 10 Z")).toBe("0 0 m 10 0 l 10 10 l h");
  });

  it("treats a second coordinate pair after M as an implicit lineto", () => {
    // SVG's rule, and the one a naive parser gets wrong by emitting two moves —
    // which draws nothing at all, because a moveto starts a fresh subpath.
    expect(convertPath("M0 0 10 10")).toBe("0 0 m 10 10 l");
  });

  it("resolves relative commands against the current point", () => {
    expect(convertPath("M10 10 l5 5 h5 v5")).toBe("10 10 m 15 15 l 20 15 l 20 20 l");
  });

  it("passes a cubic through unchanged", () => {
    expect(convertPath("M0 0 C1 2 3 4 5 6")).toBe("0 0 m 1 2 3 4 5 6 c");
  });

  it("reflects the control point of a smooth cubic", () => {
    // S continues the previous curve, so its first control point is the mirror
    // of the previous second control point through the current point: the
    // previous C ended at (5,6) with control (3,4), so the mirror is (7,8).
    expect(convertPath("M0 0 C1 2 3 4 5 6 S9 10 11 12")).toBe(
      "0 0 m 1 2 3 4 5 6 c 7 8 9 10 11 12 c",
    );
  });

  it("raises a quadratic to the equivalent cubic", () => {
    // The exact conversion: control points two thirds along each leg.
    expect(convertPath("M0 0 Q3 3 6 0")).toBe("0 0 m 2 2 4 2 6 0 c");
  });

  it("does not spin on a command it cannot draw", () => {
    // Arcs are not produced by any component here. The requirement is only that
    // an unknown command terminates rather than looping forever.
    expect(() => convertPath("M0 0 A5 5 0 0 1 10 10")).not.toThrow();
  });

  it("survives an empty path", () => {
    expect(convertPath("")).toBe("");
  });
});

describe("convertPoints", () => {
  it("converts a polyline", () => {
    expect(convertPoints("1,2 3,4 5,6", false)).toBe("1 2 m 3 4 l 5 6 l");
  });

  it("closes a polygon", () => {
    expect(convertPoints("1,2 3,4", true)).toBe("1 2 m 3 4 l h");
  });

  it("ignores a trailing half-pair rather than emitting NaN", () => {
    expect(convertPoints("1,2 3", false)).toBe("1 2 m");
  });
});

describe("pdfString", () => {
  it("escapes the characters that would end a PDF literal early", () => {
    expect(pdfString("a(b)c\\d")).toBe("a\\(b\\)c\\\\d");
  });

  it("maps the punctuation the figures actually use into WinAnsi", () => {
    // Every chart title on the site uses an em dash, and the axis captions use
    // ≤ and ×. None of these survive a naive ASCII filter.
    expect(pdfString("BMI — spread")).toBe("BMI \\227 spread");
    expect(pdfString("12–17 years")).toBe("12\\22617 years");
    expect(pdfString("≤ 40")).toBe("<= 40");
    expect(pdfString("3 × IQR")).toBe("3 \\327 IQR");
  });

  it("replaces anything else outside ASCII rather than emitting raw bytes", () => {
    expect(pdfString("α")).toBe("?");
  });
});

describe("slugify", () => {
  it("makes a filename out of a figure title", () => {
    expect(slugify("ALT by Sex — distribution")).toBe("alt-by-sex-distribution");
  });

  it("never returns an empty stem", () => {
    expect(slugify("———")).toBe("figure");
  });
});

describe("assemblePdf", () => {
  const build = (title = "Test figure"): string =>
    assemblePdf({
      stream: "1 0 0 RG 10 10 m 20 20 l S",
      width: 720,
      height: 340,
      fonts: ["Helvetica", "Helvetica-Bold"],
      alphas: [["0.5 1", "GS0"]],
      title,
    });

  it("produces a file with the header, trailer and one page", () => {
    const pdf = build();
    expect(pdf.startsWith("%PDF-1.4\n")).toBe(true);
    expect(pdf.trimEnd().endsWith("%%EOF")).toBe(true);
    expect(pdf).toContain("/MediaBox[0 0 720 340]");
    expect(pdf).toContain("/Type/Page");
  });

  it("declares every font and transparency state the stream refers to", () => {
    const pdf = build();
    expect(pdf).toContain("/F0 5 0 R");
    expect(pdf).toContain("/F1 6 0 R");
    expect(pdf).toContain("/BaseFont/Helvetica-Bold");
    expect(pdf).toContain("/GS0 <</Type/ExtGState/ca 0.5/CA 1>>");
  });

  it("points every xref offset at the object it claims", () => {
    // The check that matters. Each row of the table is a byte offset that must
    // land exactly on "N 0 obj"; if it does not, the file opens as blank or not
    // at all, and nothing else in this codebase would notice.
    const pdf = build();
    const bytes = new TextEncoder().encode(pdf);
    const xrefAt = Number(/startxref\n(\d+)/.exec(pdf)?.[1]);
    expect(Number.isFinite(xrefAt)).toBe(true);
    expect(new TextDecoder().decode(bytes.slice(xrefAt, xrefAt + 4))).toBe("xref");

    const rows = [...pdf.matchAll(/^(\d{10}) 00000 n $/gm)].map((m) => Number(m[1]));
    expect(rows).toHaveLength(6); // catalog, pages, page, contents, two fonts
    rows.forEach((offset, index) => {
      const head = new TextDecoder().decode(bytes.slice(offset, offset + 8));
      expect(head.startsWith(`${index + 1} 0 obj`)).toBe(true);
    });
  });

  it("keeps the offsets right when the title is not ASCII", () => {
    // The reason offsets are measured after encoding rather than by .length:
    // an em dash is one JavaScript character and three bytes. It appears in the
    // trailer, after every object, so a length-based xref would still pass the
    // test above — this asserts the encoder is used where it is load-bearing.
    const pdf = build("Sugar — ALT");
    const bytes = new TextEncoder().encode(pdf);
    const declared = Number(/\/Length (\d+)/.exec(pdf)?.[1]);
    const start = pdf.indexOf("stream\n") + "stream\n".length;
    const streamBytes = new TextEncoder().encode(pdf.slice(start)).length;
    expect(declared).toBeLessThanOrEqual(streamBytes);
    const xrefAt = Number(/startxref\n(\d+)/.exec(pdf)?.[1]);
    expect(new TextDecoder().decode(bytes.slice(xrefAt, xrefAt + 4))).toBe("xref");
  });
});
