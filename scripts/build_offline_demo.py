#!/usr/bin/env python
"""
Build offline/index.html -- the demo that works with no internet at all.

WHY THIS EXISTS
    Hosting the site on Render makes a network connection a hard dependency of
    the entire demo, not just of the language model. A venue with a captive
    portal, a dead hotspot, or a Render incident at the wrong moment takes the
    whole thing down, and "our website is offline" is not a recoverable answer
    to a judge standing at the table.

    So this generates a single HTML file that needs nothing: no server, no API,
    no fonts, no CDN, no JavaScript library. Put it on a laptop or a USB stick,
    open it with a double click, and it runs from file://.

WHAT IT CAN AND CANNOT DO
    It cannot run the model -- LightGBM is a compiled library and this is one
    HTML file -- so the predictions are PRE-COMPUTED here, at build time, by the
    real engine. Each example is a genuine call to engine.predict_alt(), with
    its real SHAP contributions and the same fallback explanation the live
    service generates when the language model does not answer. Nothing is typed
    by hand and nothing is approximated; what changes is that the reader picks
    from six prepared adolescents instead of moving a slider.

    That distinction is written on the page itself. A judge should be able to
    see, without asking, which parts are the live demo and which are the
    lifeboat.

USAGE
    python scripts/build_offline_demo.py            # write offline/index.html
    python scripts/build_offline_demo.py --check    # verify it is up to date

    The output is COMMITTED, like the cohort CSV and the trained model, and for
    the same reason: it is derived from things that change, so it can go stale,
    and the only way to notice is to rebuild and compare. Rebuild it after any
    retrain.
"""

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Backend"))

OUTPUT = ROOT / "offline" / "index.html"

# Six adolescents, chosen to span the model's range rather than to flatter it.
# The first is the cohort's own median (the live page's default state); the last
# two exist to show the pair a judge always asks about -- the same body, with
# sugar at the bottom and the top of the cohort -- where the bars barely move.
EXAMPLES = [
    {
        "id": "median",
        "name": "The median adolescent",
        "note": "Every input at the cohort's own median. This is where the live page starts.",
        "inputs": {},
    },
    {
        "id": "boy-high-bmi",
        "name": "Boy, high body mass",
        "note": "The combination the model is most confident about, and the study's finding in one picture.",
        "inputs": {"Male": 1, "BMI": 32.0, "TrigHDLRatio": 3.4, "HbA1c": 5.6},
    },
    {
        "id": "girl-lean",
        "name": "Girl, lean",
        "note": "The other end. Sex and body mass both push down, and they are the same two variables.",
        "inputs": {"Male": 0, "BMI": 17.5, "TrigHDLRatio": 1.1, "HbA1c": 5.0},
    },
    {
        "id": "screen",
        "name": "Boy, heavy screen time",
        "note": "A lifestyle variable on its own, with body mass held at the median.",
        "inputs": {"Male": 1, "ScreenTime": 12.0},
    },
    {
        "id": "sugar-low",
        "name": "Same boy, lowest sugar",
        "note": "Dietary sugar near the bottom of the cohort. Compare the sugar bar with the next example.",
        "inputs": {"Male": 1, "BMI": 26.0, "Sugar10g": 4.0},
    },
    {
        "id": "sugar-high",
        "name": "Same boy, highest sugar",
        "note": "The same adolescent with sugar near the top. The bar moves a little; body mass and sex do not.",
        "inputs": {"Male": 1, "BMI": 26.0, "Sugar10g": 26.0},
    },
]

# Deliberately its own stylesheet rather than a copy of the site's. The site's
# is 60 KB of a design system this page uses a tenth of, and a copy would go
# stale the first time either one changed. This is the same type scale and the
# same one blue, written out small enough to read.
STYLE = """
:root {
  --ink: #1d1d1f; --ink-2: #515154; --ink-3: #6e6e73;
  --line: #d2d2d7; --surface: #fff; --surface-2: #f5f5f7;
  --accent: #0071e3; --neg: #d03b3b;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0 20px 80px;
  font: 17px/1.53 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  color: var(--ink); background: var(--surface);
}
main { max-width: 940px; margin: 0 auto; }
header { padding: 64px 0 40px; text-align: center; }
h1 { font-size: clamp(2.1rem, 5vw, 3.1rem); font-weight: 600; letter-spacing: -0.017em; margin: 0 0 16px; }
h2 { font-size: 1.75rem; font-weight: 600; letter-spacing: -0.014em; margin: 56px 0 8px; }
.eyebrow { color: var(--accent); font-size: 0.8125rem; font-weight: 500; letter-spacing: 0.06em; text-transform: uppercase; margin: 0 0 12px; }
.lede { color: var(--ink-2); max-width: 62ch; margin: 0 auto; }
.note { color: var(--ink-3); font-size: 0.9375rem; }
.banner {
  margin: 32px 0; padding: 20px 24px; border-radius: 18px;
  background: var(--surface-2); color: var(--ink-2); font-size: 0.9375rem; line-height: 1.5;
}
.banner b { color: var(--ink); }
.tabs { display: flex; flex-wrap: wrap; gap: 8px; margin: 28px 0 0; }
.tab {
  padding: 9px 18px; border: 1px solid var(--line); border-radius: 980px;
  background: var(--surface); color: var(--ink-2);
  font: inherit; font-size: 0.9375rem; cursor: pointer;
}
.tab[aria-selected="true"] { border-color: var(--accent); background: var(--accent); color: #fff; }
.card { display: none; margin-top: 28px; }
.card.is-shown { display: block; }
.headline { display: flex; flex-wrap: wrap; gap: 40px; margin: 24px 0 8px; }
.headline div { min-width: 150px; }
.big { font-size: 2.6rem; font-weight: 600; letter-spacing: -0.02em; }
.k { color: var(--ink-3); font-size: 0.8125rem; }
svg { display: block; width: 100%; height: auto; margin: 20px 0 4px; }
.bar-up { fill: var(--accent); fill-opacity: 0.72; }
.bar-down { fill: var(--neg); fill-opacity: 0.72; }
.axis { stroke: #86868b; stroke-width: 1; }
.grid { stroke: var(--line); stroke-width: 1; }
text { font: 11px -apple-system, sans-serif; fill: var(--ink-3); }
text.row { fill: var(--ink-2); }
table { width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 0.9375rem; }
th, td { text-align: right; padding: 11px 12px; border-bottom: 1px solid var(--line); }
th:first-child, td:first-child { text-align: left; }
th { color: var(--ink-3); font-weight: 400; font-size: 0.8125rem; }
td { font-variant-numeric: tabular-nums; }
.prose { padding: 22px 24px; border-radius: 18px; background: var(--surface-2); margin: 20px 0; }
.prose p { margin: 0; font-size: 1.1875rem; }
.prose .note { margin-top: 12px; font-size: 0.8125rem; }
footer { margin-top: 72px; padding-top: 28px; border-top: 1px solid var(--line); color: var(--ink-3); font-size: 0.875rem; }
"""

# The interactivity is one function. No framework, no build step, and it works
# from file:// where a module script or a fetch would not.
SCRIPT = """
document.querySelectorAll('.tab').forEach(function (tab) {
  tab.addEventListener('click', function () {
    document.querySelectorAll('.tab').forEach(function (t) {
      t.setAttribute('aria-selected', String(t === tab));
    });
    document.querySelectorAll('.card').forEach(function (card) {
      card.classList.toggle('is-shown', card.id === tab.dataset.card);
    });
  });
});
"""


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def bars(prediction: dict) -> str:
    """The contribution chart, as inline SVG.

    A hand-written twin of frontend/components/figures/ContributionChart.tsx and
    deliberately a simplified one: same diverging form, same fixed zero, same
    two colours, no tooltip. Duplication is the right trade here -- the React
    component cannot run in a file with no bundler, and a chart drawn from the
    same numbers in the same shape is what makes the lifeboat recognizable as
    the same demo.
    """
    drivers = prediction["drivers"]
    width, row_h, label_w, value_w, top, bottom = 720, 30, 175, 70, 34, 30
    height = top + len(drivers) * row_h + bottom
    left, right = label_w, width - value_w
    mid = (left + right) / 2
    span = max(2.0, max(abs(d["percent_of_alt"] or 0) for d in drivers))
    span = 5 * (int(span / 5) + 1)
    half = (right - left) / 2

    def x(percent: float) -> float:
        return mid + (percent / span) * half

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="'
        f'How each input moved the predicted ALT of {esc(prediction["predicted_alt"])} U/L">'
    ]
    for tick in (-span, -span / 2, 0, span / 2, span):
        css = "axis" if tick == 0 else "grid"
        parts.append(
            f'<line class="{css}" x1="{x(tick):.1f}" x2="{x(tick):.1f}" '
            f'y1="{top - 8}" y2="{top + len(drivers) * row_h}"/>'
        )
        parts.append(
            f'<text x="{x(tick):.1f}" y="{top + len(drivers) * row_h + 16}" '
            f'text-anchor="middle">{"+" if tick > 0 else ""}{tick:g}%</text>'
        )
    parts.append(
        f'<text x="{x(-span / 2):.1f}" y="{top - 15}" text-anchor="middle">lowers the prediction</text>'
        f'<text x="{x(span / 2):.1f}" y="{top - 15}" text-anchor="middle">raises the prediction</text>'
    )
    for index, driver in enumerate(drivers):
        percent = driver["percent_of_alt"] or 0
        y = top + index * row_h
        end, zero = x(percent), x(0)
        parts.append(
            f'<text class="row" x="{left - 10}" y="{y + row_h / 2 + 4:.0f}" '
            f'text-anchor="end">{esc(driver["label"])}</text>'
            f'<rect class="{"bar-down" if percent < 0 else "bar-up"}" '
            f'x="{min(zero, end):.1f}" y="{y + row_h * 0.2:.0f}" '
            f'width="{max(1.0, abs(end - zero)):.1f}" height="{row_h * 0.6:.0f}"/>'
            f'<text x="{right + 8}" y="{y + row_h / 2 + 4:.0f}">'
            f"{'+' if percent > 0 else ''}{percent:.1f}%</text>"
        )
    parts.append("</svg>")
    return "".join(parts)


def card(example: dict, prediction: dict, explanation: str, first: bool) -> str:
    rows = "".join(
        f"<tr><td>{esc(d['label'])}</td><td>{esc(d['display'])}</td>"
        f"<td>{esc(d['cohort_median_display'] or '—')}</td>"
        f"<td>{'+' if (d['percent_of_alt'] or 0) > 0 else ''}"
        f"{(d['percent_of_alt'] or 0):.2f}%</td>"
        f"<td>{d['contribution_log']:.5f}</td></tr>"
        for d in prediction["drivers"]
    )
    return f"""
<section class="card{" is-shown" if first else ""}" id="{esc(example["id"])}">
  <p class="note">{esc(example["note"])}</p>
  <div class="headline">
    <div><p class="big">{esc(prediction["predicted_alt"])} U/L</p><p class="k">Predicted ALT</p></div>
    <div><p class="big">{esc(prediction["baseline_alt"])} U/L</p><p class="k">Model's starting point</p></div>
    <div><p class="big">{esc(prediction["reference"]["elevated_threshold"])} U/L</p>
         <p class="k">Elevated-ALT line ({esc(prediction["reference"]["sex"])})</p></div>
  </div>
  {bars(prediction)}
  <p class="note">Change in predicted ALT, from a baseline of
     {esc(prediction["baseline_alt"])} U/L. The baseline plus every bar equals
     {esc(prediction["predicted_alt"])} U/L exactly — these are SHAP contributions,
     so the chart is a decomposition rather than a ranking.</p>
  <table>
    <thead><tr><th>Input</th><th>Entered</th><th>Cohort median</th>
      <th>Moved ALT by</th><th>ln(ALT) contribution</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <div class="prose">
    <p>{esc(explanation)}</p>
    <p class="note"><b>Written by the project, not by a language model.</b>
      This page has no internet connection, so it ships the same fallback text
      the live service generates when the language model does not answer. The
      numbers above never came from a language model in the first place.</p>
  </div>
  <p class="note">{esc(prediction["reference"]["means"])}</p>
</section>
"""


def build() -> str:
    import engine
    import predict_api

    headline = engine.headline()
    model_card = engine.predictor_card()
    scores = model_card["validation"]

    tabs, cards = [], []
    for index, example in enumerate(EXAMPLES):
        prediction = engine.predict_alt(example["inputs"])
        explanation = predict_api._canned_explanation(prediction)
        tabs.append(
            f'<button class="tab" role="tab" data-card="{esc(example["id"])}" '
            f'aria-selected="{"true" if index == 0 else "false"}">'
            f"{esc(example['name'])}</button>"
        )
        cards.append(card(example, prediction, explanation, first=index == 0))

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Predicting adolescent liver stress — offline demo</title>
<!--
  GENERATED FILE. Do not edit by hand.
  Rebuild with: python scripts/build_offline_demo.py
  Every number below was produced by Backend/engine.py at build time.
-->
<style>{STYLE}</style>
</head>
<body>
<main>
<header>
  <p class="eyebrow">Offline demo</p>
  <h1>Predicting adolescent liver stress</h1>
  <p class="lede">A gradient boosting model on {esc(model_card["n"])} U.S. adolescents from
    NHANES 2017–2018, with an exact breakdown of every prediction. By Anirudh Gupta.</p>
</header>

<div class="banner">
  <b>This is the backup copy.</b> It needs no internet connection, no server and
  no API key — which is also what it cannot do: the model itself is a compiled
  library, so the six adolescents below were run through it in advance rather
  than being typed in live. Everything else is real. The contributions are the
  model's own SHAP values, and they add up.
  <br><br>
  <b>The live version</b> lets you move the seven inputs yourself and has a
  language model describe the result. Same model, same numbers.
</div>

<h2>What the study found</h2>
<p>Across {esc(headline["n"])} adolescents, dietary sugar did <b>not</b> independently predict
  blood ALT once body mass was accounted for (p = {esc(headline["sugar_p"])}). What did:
  body mass, sex — boys averaged {esc(headline["sex_difference_in_alt"]["male"])} U/L against
  {esc(headline["sex_difference_in_alt"]["female"])} U/L for girls — and the triglyceride/HDL
  ratio (standardized β = {esc(headline["trig_hdl_beta"])}, p = {esc(headline["trig_hdl_p"])}).
  {esc(headline["elevated_alt_percent"])}% sat above the sex-specific pediatric screening line.</p>
<p class="note">{esc(headline["not_causal"])}</p>

<h2>The model, and how well it works</h2>
<p>The same specification the study's primary test uses, fitted by gradient boosting
  instead of weighted least squares. Out of fold it scores
  R² = {esc(scores["gradient_boosting"]["r_squared_log_alt"])} on ln(ALT) against
  R² = {esc(scores["linear_model_b_with_bmi"]["r_squared_log_alt"])} for the study's linear model
  on identical folds — so the trees find a little structure the regression cannot express.</p>
<p>Given a free hand, the model leans on body mass and sex, then the metabolic markers,
  and puts dietary sugar second from last. That is the study's null result reached a
  second way, by a method with no stake in it.</p>
<p class="note">{esc(scores["note"])}</p>

<h2>Six adolescents</h2>
<div class="tabs" role="tablist">{"".join(tabs)}</div>
{"".join(cards)}

<footer>
  <p>{esc(model_card["caveat"])}</p>
  <p>Generated from Backend/engine.py — the same code that serves the live site.
     Elevated-ALT thresholds: {esc(model_card["elevated_alt_source"])}.</p>
  <p>© 2026 Anirudh Gupta</p>
</footer>
</main>
<script>{SCRIPT}</script>
</body>
</html>
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the committed page matches a fresh build; write nothing.",
    )
    args = parser.parse_args(argv)

    page = build()
    if args.check:
        if not OUTPUT.is_file():
            print(f"{OUTPUT.relative_to(ROOT)} is missing -- run this without --check")
            return 1
        if OUTPUT.read_text() != page:
            print(
                f"{OUTPUT.relative_to(ROOT)} is stale (the model or the study moved)."
            )
            print("Fix with: python scripts/build_offline_demo.py")
            return 1
        print(f"{OUTPUT.relative_to(ROOT)} is up to date.")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(page)
    print(
        f"Wrote {OUTPUT.relative_to(ROOT)} ({len(page) / 1024:.0f} KB, {len(EXAMPLES)} examples)."
    )
    print("Open it with a double click -- no server needed. Copy it to a USB stick.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
