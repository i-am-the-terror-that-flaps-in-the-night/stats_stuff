# stats-and-more

A **descriptive-statistics engine**, the **pre-specified analysis** it was built to run, and a
**FastAPI + React** service that serves both. The research question is whether dietary sugar
predicts early liver stress in U.S. adolescents; the dataset is
[NHANES 2017–2018](https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/).

**The finding: it doesn't — not independently of body mass.** Sex and the triglyceride/HDL ratio
do. See [The study](#the-study).

## What this repo does

| Component | Entry point | What it does |
|---|---|---|
| **Stats engine** | `Backend/engine.py` (part one) | General-purpose basic/medium/advanced/expert/categorical tiers on any dataframe |
| **Cohort derivation** | `Backend/engine.py` (part two) | Turns the raw 412-column NHANES merge into the 699-adolescent analytic cohort, with a logged attrition table |
| **The study** | `Backend/engine.py` (part three) | The pre-specified ten-step analysis: weighted regressions, mediation, dose-response, risk score |
| **Web service** | `Backend/app.py` | FastAPI: `/healthz`, the JSON API, and the built frontend; deploys to Render |
| **Study API** | `Backend/study_api.py` | `/api/study/*` — the study's results over HTTP |
| **Studio API** | `Backend/studio.py` | `/api/datasets` and `/api/runs` — dataset inventory and the local SQLite run log |
| **Frontend** | `frontend/` | React 19 + Vite 8 + TypeScript 7 SPA: the dashboard, the Study page, the static pages and the Studio |

All three live in one file, in three labelled parts. The boundary between them is still real, it
is just a section banner rather than a separate module: part one knows nothing about livers — hand
it any spreadsheet and it will describe any column, which is what makes it reusable. Part three
answers one fixed set of questions about one cohort with every variable's role decided in advance.
Because those roles are pre-specified, the study may do things the engine's tiers refuse to do on
an arbitrary column (apply a sex-specific clinical threshold, decompose an association into direct
and mediated parts). `DataAnalyzer` still has exactly seven methods; the cohort builder and the
protocol are module-level code beside it, not an eighth tier inside it.

## The study

**Sex and metabolic factors, not dietary sugar, predict early-stage liver stress in U.S.
adolescents.** A secondary analysis of NHANES 2017–2018, *n* = 699 adolescents aged 12–17.

Alanine aminotransferase (ALT) leaks from stressed liver cells, so it is an early marker of the
metabolic liver disease that used to be an adult diagnosis and increasingly is not. The common
assumption is that dietary sugar drives it directly. This analysis tests that, and finds:

- **Dietary sugar does not independently predict ALT once BMI is in the model** (*p* = 0.58). The
  association is not significant before adjustment either (*p* = 0.15).
- **No dose-response.** Mean ALT does not climb across sugar quartiles (trend *p* = 0.15) — 16.3,
  15.5, 17.1, 15.4 U/L from lowest to highest. A gradient is one of the stronger observational
  arguments for a real effect, and there isn't one.
- **The triglyceride/HDL ratio does predict ALT** (standardized β = 0.14, *p* = 0.005), and adding
  it and HbA1c to a lifestyle-only model raises R² from 0.106 to 0.154 (joint *p* = 0.008).
- **Sex matters more than diet.** Weighted mean ALT is 19.1 U/L in boys against 12.9 U/L in girls.
- **The composite 0–6 risk score separates cleanly**: mean ALT rises 11.4 → 30.3 U/L across the
  bands and elevated-ALT prevalence 1.1% → 40%, beating every single factor on R². This one is
  exploratory — see the caveats below.
- **The null survives every sensitivity check**: two-day averaged sugar, unweighted, raw ALT
  instead of log, and energy-adjusted.

A null primary result is a result. It says interventions aimed only at sugar, without addressing
weight and lipid dysregulation, are unlikely to move adolescent liver stress.

### How the numbers are computed

Every estimate is **weighted** by the day-1 dietary weight (`WTDRD1`), so it describes U.S.
adolescents rather than whoever NHANES recruited. Every standard error is **cluster-robust** by
PSU within stratum, so the clustered sample design doesn't make results look more precise than
they are. There are 30 clusters (15 strata × 2 PSUs) — enough for the correction to be worth
making, few enough that the robust *p*-values are approximate.

ALT is modelled as `ln(ALT)`; the raw values are strongly right-skewed and would otherwise dominate
a least-squares fit. Sugar coefficients are reported per 10 g/day, because a per-gram coefficient
is below what a 24-hour recall can resolve.

### What it will not claim

Nothing here is causal. The data are cross-sectional. The mediation step decomposes an
*association* into two associations and is labelled that way — calling the BMI-carried part
"mediated" would require sugar to precede BMI to precede ALT with no unmeasured common cause, and
one visit's data supports none of that.

The risk score is **exploratory and relative**. Five of its six components are cut at this cohort's
own median, as the revised protocol's Step 9 specifies (there is no published "grams of sugar per
day above which a 14-year-old is at risk",
and adolescent BMI is scored against age- and sex-specific growth-chart percentiles this project
doesn't carry). So it ranks these adolescents against each other, its thresholds would move in
another population, and it is evaluated on the same data that defined its cut points — which
flatters it. It needs validation in a separate sample before it means anything as a screening tool.

The sex and subgroup analyses are exploratory and uncorrected for multiplicity, and say so.

### Three departures from the written protocol

Each is a case where the protocol names a variable that doesn't mean what its name suggests, or
doesn't exist at the stated sample size. All three are documented at their definitions in
`Backend/engine.py`'s cohort section.

| # | Protocol says | What the data says | Resolution |
|---|---|---|---|
| 1 | Exclude on Hepatitis B surface antigen, `HEPB_S_J` | `HEPB_S_J` is the surface **antibody** file — a marker of *vaccination*, positive in 179 of these adolescents | Exclude on `LBDHBG` (`HEPBD_J`), the actual surface antigen. Excluding on antibody would have thrown out the vaccinated |
| 2 | Triglycerides from `TRIGLY_J` (`LBXTR`) | Fasting-subsample only — present for 341 adolescents, which cannot support *n* = 695 | Use `LBXSTR`, the same analyte on the MEC biochemistry panel (749 present). The two correlate at *r* = 0.997 where both exist; `LBXSTR` runs ~14 mg/dL higher because it isn't fasting, so it's sound for ranking and regression and its cut point is a cohort median rather than an absolute clinical line |
| 3 | Screen time as a model variable | Missing for 113 otherwise-eligible adolescents | Kept as a variable with its own reduced *n* (586) rather than an entry criterion. Requiring it would cost 16% of the sample to serve the two analyses that use it |

**On the sample size:** the protocol states *n* = 695; applying the rules it states yields **699**.
Every additional exclusion the protocol mentions — pregnancy, an unreliable dietary recall, a
non-positive survey weight, a non-positive ALT — is already true of all 699, so none of them closes
the gap. The difference is reported rather than engineered away.

### The ten steps

| # | Step | Grade | *n* |
|---|---|---|---|
| 1 | Cohort derivation and attrition | supporting | 699 |
| 2 | Weighted descriptive profile | supporting | 699 |
| 3 | Outcome distribution and log transformation | supporting | 699 |
| 4 | **Primary A** — total association of sugar with ALT | **primary** | 699 |
| 5 | **Primary B** — sugar adjusted for BMI, and the mediation comparison | **primary** | 699 |
| 6 | Dose-response across sugar quartiles | supporting | 699 |
| 7 | Mechanism — triglyceride/HDL versus dietary sugar | supporting | 699 |
| 8 | Incremental value of the metabolic blood markers | supporting | 586 |
| 9 | Sex differences | exploratory | 699 |
| 10 | Composite 0–6 risk score | exploratory | 586 |
| — | Sensitivity checks on the primary result | supporting | varies |

The grades are pre-specified and they matter: they are what stops a null primary result being
quietly replaced by whichever subgroup happened to clear *p* < 0.05.

## Project structure

```
stats_and_more/
├── main.py                  # Deploy entry point: re-exports Backend/app.py (Render's `uvicorn main:app`)
├── Backend/
│   ├── engine.py            # ONE analysis file, four parts:
│   │                        #   1. the five generic stats tiers (DataAnalyzer)
│   │                        #   2. the cohort derivation (+ `build-cohort` CLI)
│   │                        #   3. the pre-specified ten-step study
│   │                        #   4. the LightGBM predictor (+ `train-model` CLI)
│   ├── model/               # The trained predictor -- a committed build artifact
│   │   ├── alt_lgbm.txt     #   the booster, LightGBM's own text format (~44 KB)
│   │   └── alt_lgbm.json    #   the model card: features, ranges, CV scores, caveats
│   ├── study_api.py         # /api/study/*
│   ├── predict_api.py       # /api/predict/* -- the demo, and the OpenRouter call
│   ├── app.py               # FastAPI service: /healthz, the JSON API, serves frontend/dist
│   ├── figures_api.py       # /api/figures/* chart aggregates
│   ├── lab_api.py           # /api/lab/* Studio experiments
│   └── studio.py            # /api/datasets and /api/runs
├── Data/
│   ├── nhanes_adolescent.csv  # THE LIVE DATASET: the analytic cohort (~100 KB, tracked)
│   ├── cohort_attrition.json  # The attrition log, derived beside it (655 B, tracked)
│   ├── nhanes_analytic.csv    # Full raw NHANES merge, 412 columns, 17 MB (Git LFS)
│   ├── nhanes.csv             # Earlier curated 18-column slice, superseded (tracked)
│   └── data.csv               # Small synthetic practice dataset (tracked)
├── extra_data/
│   ├── csv_data/            # NHANES component CSVs (gitignored)
│   └── PDF_explanations/    # Variable codebook PDFs -- the source for every coding decision
├── offline/
│   └── index.html           # The no-internet demo: one self-contained file, generated
├── frontend/                # React + Vite + TypeScript SPA (built to frontend/dist, gitignored)
│   └── src/
│       ├── routes/          # Overview, Study, Predict, Figures, Methodology, Benchmarks, Changelog, Studio, Guide
│       ├── components/      # Shell, BootLoader, ResultView, Page primitives
│       ├── lib/             # api.ts, hooks.ts, format.ts, scales.ts
│       └── types/engine.ts  # API payload types
├── tests/
│   ├── test_engine.py       # The engine's arithmetic and its statistical semantics
│   ├── test_cohort.py       # Code decoding, exclusions, no-imputation, artifact drift
│   ├── test_study.py        # Survey design, shared samples, protocol fidelity
│   └── test_predictor.py    # SHAP additivity, the specification, the LLM failover
├── .gitattributes           # Git LFS: Data/nhanes_analytic.csv
├── render.yaml              # Render Blueprint
├── pyproject.toml           # Dependencies (managed with uv)
└── requirements.txt         # Pip-compatible pin list -- what Render builds from
```

## Requirements

- **Python 3.14.6+** (see `.python-version`)
- [uv](https://docs.astral.sh/uv/) recommended, or pip
- [Git LFS](https://git-lfs.com/), only if you want to rebuild the cohort from the raw merge

## Setup

```bash
git clone <repo-url>
cd stats_and_more

uv sync                              # with uv (recommended)
# ...or with pip:
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

git lfs pull                         # optional -- only needed to rebuild the cohort
```

`git lfs pull` is optional on purpose. The app reads the small committed cohort and never touches
the 17 MB raw merge, so a checkout that skips it still runs the site and passes every test that
doesn't specifically check the derivation (those skip themselves).

## The data pipeline

```
extra_data/csv_data/*.csv    16 NHANES component files, joined on SEQN
        │
        ▼
Data/nhanes_analytic.csv     9,254 participants × 412 raw-coded columns   [Git LFS]
        │
        │  engine.py part 2   ── age 12–17, viral hepatitis excluded,
        │                        answer codes decoded, complete core variables
        ▼
Data/nhanes_adolescent.csv   699 adolescents × 21 named columns           [tracked, ~100 KB]
        │
        ├──►  engine.py part 1    the five generic tiers
        └──►  engine.py part 3    the ten-step study
```

Rebuild the cohort (needs the LFS file):

```bash
python Backend/engine.py build-cohort          # rebuild, print the attrition table
python Backend/engine.py build-cohort --check  # verify the artifacts still match the code
```

It writes two files: `Data/nhanes_adolescent.csv` (the cohort) and `Data/cohort_attrition.json`
(the log below). `--check` is the drift guard for both, and CI runs it. They are build artifacts;
without this check a change to the derivation could ship while the files kept the old numbers.

The attrition table it prints is the real one:

```
step                          n  removed
NHANES 2017-2018 merge     9254        0
Adolescents                 907     8347
No viral hepatitis          907        0
Complete core variables     699      208
Positive dietary weight     699        0
```

The two zero-removal rules are applied and logged rather than skipped, because *"we checked and it
was zero"* and *"we never checked"* are different claims and only one of them is defensible.

### Why the cohort is committed and the raw merge is in LFS

The deployed app reads a 100 KB tracked file and a 655-byte JSON log. It never needs an LFS object,
so a Render dyno that never ran `git lfs pull` boots correctly, and the cold start pays milliseconds
instead of parsing 17 MB of mostly-irrelevant columns. The raw merge is still under version
control — it is the provenance for everything else — just not in the ordinary object history.

The attrition log is committed for the same reason, and it is worth being precise about why, because
the code originally rebuilt it live and guarded that with `RAW_CSV.is_file()`. A checkout that never
fetched the LFS object does not leave *nothing* at that path — it leaves a 133-byte pointer file,
which `is_file()` reports as present. So on Render the guard passed, `read_csv` parsed the pointer
metadata as a header, and every study endpoint answered `500`. `raw_merge_available()` asks the
question the guard meant to ask, and the committed log means production has no reason to ask it at
all: rebuilding it cost 109 MB of peak RSS — more than pandas and scipy together, on a 512 MB
instance — to recompute five rows that had not changed since the last deploy.

### Variables

| Cohort column | NHANES variable | Codebook | Role |
|---|---|---|---|
| `ALT` | `LBXSATSI` | `BIOPRO_J` | Outcome — liver-cell leakage |
| `TotalSugars`, `TotalSugarsDay2` | `DR1TSUGR`, `DR2TSUGR` | `DR1TOT_J`, `DR2TOT_J` | Primary exposure (+ sensitivity) |
| `ScreenTime` | `PAQ710` + `PAQ715` | `PAQY_J` | Lifestyle — decoded from bands, see below |
| `BMI` | `BMXBMI` | `BMX_J` | Confounder / mediator |
| `Triglycerides`, `HDLCholesterol`, `TrigHDLRatio` | `LBXSTR`, `LBDHDD` | `BIOPRO_J`, `HDL_J` | Mechanism |
| `HbA1c` | `LBXGH` | `GHB_J` | Mechanism |
| `Age`, `Sex`, `RaceEthnicity`, `IncomeRatio` | `RIDAGEYR`, `RIAGENDR`, `RIDRETH3`, `INDFMPIR` | `DEMO_J` | Controls / descriptive |
| `Energy` | `DR1TKCAL` | `DR1TOT_J` | Sensitivity |
| `DietWeight`, `SurveyPSU`, `SurveyStratum` | `WTDRD1`, `SDMVPSU`, `SDMVSTRA` | `DEMO_J` | Survey design |
| `ALTElevated`, `RiskScore` | constructed | — | Derived |

**Screen time is decoded, not averaged.** `PAQ710`/`PAQ715` are banded answers where two of the
bands aren't numbers: `8` means "does not watch TV / use a computer" — a real zero — and `77`/`99`
are "refused"/"don't know". Left alone, those enter a mean as the two heaviest screen users in the
study. `0` ("less than 1 hour") maps to the band midpoint 0.5, and `5` ("5 hours or more") is
right-censored at 5.0, which compresses the top of the distribution and biases any screen-time
association toward zero.

**Bookkeeping columns are excluded from the explorer.** `SEQN` and the survey design codes parse
perfectly as numbers and mean nothing when averaged, so `cohort.NON_ANALYTIC_COLUMNS` keeps them
out of the column list the website offers while leaving them in the dataframe the study needs.

**Elevated ALT uses sex-specific pediatric thresholds** — 26 U/L for boys, 22 for girls (Schwimmer
et al. 2010, adopted by NASPGHAN 2017). These sit far below the ~40 U/L adult reference ceiling a
hospital lab prints, which is the point: an adult ceiling misses most pediatric liver disease.
They live in the cohort section rather than in `CLINICAL_THRESHOLDS` because that table
deliberately refuses sex-specific cutoffs — it applies to a bare column with no guarantee sex is
even present, whereas here it is required for every participant.

## Web service

```bash
./run.sh           # both servers: API on :8000, app on :5173  <- open :5173
./run.sh build     # build the frontend, then serve it from FastAPI at :8000
```

`./run.sh` is the everyday command. Open **:5173**, not :8000: Vite serves the app with hot reload
and proxies `/api` to uvicorn, so there is no CORS in the loop. Port 8000 serves whatever was last
built into `frontend/dist`, which in development is usually stale.

To run either side alone:

```bash
uv run uvicorn main:app --reload   # backend only
cd frontend && npm run dev         # frontend only (no API)
```

### Routes

| Route | Returns |
|---|---|
| `GET /healthz` | Liveness probe for Render |
| `GET /api/overview` | Dataset telemetry: shape, analyzable/categorical/excluded split |
| `GET /api/columns` | Numeric and categorical columns, plus label values |
| `GET /api/stats/{column}` | The basic tier (kept for backward compatibility) |
| `GET /api/analyze/{tier}/{column}` | Any tier, optional `?group=` |
| `GET /api/study` | The whole ten-step study plus sensitivity checks |
| `GET /api/study/headline` | The summary-card numbers |
| `GET /api/study/steps` | Step index: names, titles, claim grades |
| `GET /api/study/step/{name}` | One step |
| `GET /api/study/cohort` | The attrition table |
| `GET /api/predict/model` | The predictor's model card: inputs, ranges, CV scores |
| `POST /api/predict` | One prediction with its exact SHAP decomposition |
| `POST /api/predict/explain` | The same, narrated by a language model (never fails) |
| `POST /api/predict/ask` | A follow-up question about that prediction |
| `GET /api/predict/questions` | Starter questions for the question box |
| `GET /api/predict/llm` | Whether the language model is configured (setup check) |
| `GET /api/figures/*` | Chart aggregates: histogram, box, scatter, correlation |
| `GET /api/lab/*` | Studio experiments: cohort, sample-size, bootstrap, outliers, screen |
| `GET /api/datasets`, `/api/runs` | Dataset inventory and the run log |
| `GET /`, `/assets/*`, anything else accepting HTML | The SPA shell and its bundle |

Step names for `/api/study/step/{name}`: `cohort`, `profile`, `distribution`, `total-effect`,
`direct-effect`, `dose-response`, `mechanism`, `incremental`, `sex`, `risk-score`, `sensitivity`.

### What the engine will and won't claim

Every block of output carries a `layer` key — `descriptive`, `inferential` or `predictive` — naming
how strong a claim it supports. Nothing is ever labelled causal. Every *p*-value ships with an
effect size, because statistical significance and practical importance are different questions, and
with the correct definition of what a *p*-value means attached.

The study module adds one thing on top: `p_value_text`, which reads `"< 0.0001"` where the rounded
value would print as a flat `0`. A displayed "p = 0" reads as certainty, which is the one claim a
*p*-value never makes.

Clinical thresholds come from `CLINICAL_THRESHOLDS` (published guideline values, each with its
source), never from the dataset's own median. Because a cutoff is a number *plus a unit*, each
entry stores its cutoff per unit and the band a population median plausibly falls in. Before
applying anything the engine checks the column's median against that band: if the data looks like
mmol/L when the cutoff is mg/dL it refuses and names the unit it suspects, rather than reporting a
precise, confident, wrong prevalence. Declare units explicitly with
`expert_analysis(column, units="mmol/L")`.

### Missing values

Nothing is ever imputed. Every tier does complete-case analysis, so a regression on six predictors
can run on far fewer people than the file contains — watch the `n` reported in each block, which is
the sample the numbers actually describe. The study module goes further and builds a fresh frame
per analysis, so two models being *compared* are forced onto one shared sample: a change in R²
measured across two different samples measures the sample, not the predictors.

## Frontend

```bash
npm run build      # tsc -b (typecheck) then vite build -> frontend/dist
npm run typecheck  # types only
```

`frontend/dist` is gitignored and built on deploy (see `render.yaml`), so there is no committed
bundle that can drift from its source.

Two things worth knowing before changing the build:

- **`base` must stay `"/"`.** `index.html` is served for every deep link, so a relative base makes
  `/studio/runs` resolve `./assets/index.js` against `/studio/` and 404 — the HTML still returns
  200, so the page just goes blank with no build or type error to warn you.
- **Import from `react-router`, not `react-router-dom`.** v7 merged everything into the one
  package; `react-router-dom` is a legacy re-export whose 7.12–8.2 range carries a CSRF advisory.

### Pages

- **Overview** — the live analysis widget and dataset telemetry
- **Study** — the ten steps, each with its claim grade; models load when a step is opened
- **Predict** — the interactive demo: seven inputs, a predicted ALT, and an exact SHAP breakdown
- **Figures** — histograms, box plots, scatter and the correlation matrix
- **Methodology** — the pipeline, the tiers, the formulas and the missing-data rule
- **Studio** (`/studio`, `/guide`) — the column and dataset browser, the experiments, the run log

The Studio's run log is a local SQLite file (`Backend/studio_runs.db`, gitignored). Render's free
tier has no persistent disk, so it is a personal lab notebook, not shared state the site depends
on. An empty log is the normal online state.

## The prediction demo

The study answers a hypothesis. This answers a different question — *given these seven numbers,
what ALT would you guess, and which of the seven moved the guess?* — and it is the part of the
site a judge can touch.

**Model.** LightGBM gradient-boosted trees on the same 586 adolescents and the *same
specification* as the study's primary test (Model B with BMI: sugar, screen time, age, sex,
Trig/HDL, HbA1c, BMI), predicting `ln(ALT)`, weighted by the survey weight. Nothing was added
because it helped and nothing was dropped because it did not, so the two are two estimators of one
pre-specified model rather than two different models.

**It is also a check on the study.** Given a free hand — no linearity assumed, interactions
allowed — the tree model leans on body mass and sex, then the metabolic markers, and puts dietary
sugar second from last. That is the study's null result reached a second way, by a method with no
stake in it.

| Estimator | Out-of-fold R² on ln(ALT) | Mean absolute error |
|---|---|---|
| Gradient boosting | 0.2786 | 5.43 U/L |
| The study's linear Model B | 0.2400 | 5.58 U/L |

Both scored on identical folds, **grouped by sampling cluster** rather than by participant — two
adolescents from the same sampled location are more alike than two strangers, and splitting them
across the train/test line lets a model see its own answer. The number of boosting rounds is chosen
*inside* each training fold by a second cross-validation, so the reported score pays for that
choice instead of hiding it.

### SHAP without the `shap` package

Every prediction ships with exact per-feature SHAP contributions from LightGBM's own
`pred_contrib=True`, which runs TreeSHAP inside the booster — the same numbers
`shap.TreeExplainer` returns, because it delegates to this implementation for LightGBM models.

That is a deliberate substitution. `shap` pulls in scikit-learn, numba, llvmlite, cloudpickle,
tqdm and slicer; this service runs on 512 MB of which imported libraries are already ~184 MB, and
numba has no wheel for the Python version this project pins. LightGBM alone is a 3.5 MB wheel and
adds ~10 MB resident on top of the stack this service already loads. Same numbers, none of the
weight.

The contributions are additive by construction — base value + the seven contributions = the
prediction, exactly — which is what makes the chart a decomposition rather than an attribution
heuristic. `tests/test_predictor.py` pins that identity.

### Training is offline; the model is committed

```bash
uv run python Backend/engine.py train-model          # refit, write Backend/model/
uv run python Backend/engine.py train-model --check  # CI's drift guard
```

Same bargain as the cohort CSV: Render's filesystem is ephemeral and 0.1 vCPU is not something to
run a fit on inside a request, so training happens locally and the booster plus its model card are
committed. `--check` retrains in memory and compares — **structure exactly** (features, n, clusters,
rounds, hyperparameters, input ranges, importance order) and **behaviour to 1e-6** across the whole
cohort. It is not a byte diff on purpose: the model is trained on a Mac and verified on x86 Linux,
and nothing in LightGBM promises bit-identical split thresholds across architectures. A guard that
can go red when nothing is wrong is a guard nobody trusts.

Rebuild `offline/index.html` after any retrain (see below). CI checks both.

### The language model

`POST /api/predict/explain` hands the finished prediction and its contributions to a hosted model
as *text* and gets two to four sentences back. **The language model does not predict anything**,
never sees the cohort, and cannot reach the booster. If it returns something wrong, every number on
the page is still the number gradient boosting produced.

That boundary is enforced by the route split, not by a promise: `/api/predict` makes no outbound
call, the frontend renders it first, and only then asks for prose.

**Failover, three steps** (`Backend/predict_api.py`):

1. **Nemotron 3.5 Lightning** (`nvidia/nemotron-3.5-lightning`), 3 s timeout.
2. On any failure — timeout, HTTP error, malformed body, a slug OpenRouter has retired —
   **Nemotron 3 Ultra** (`nvidia/nemotron-3-ultra-550b-a55b`), 8 s.
3. On a second failure, a **generated** explanation. Not a fixed string: it is assembled from the
   same SHAP contributions the model would have been given, so it names *this* reader's actual top
   drivers in their actual directions. The response says which of the three answered, and the page
   labels a fallback as one rather than passing it off.

Reasoning is switched off in the request. A reasoning model that spends twenty seconds thinking in
front of a judge reads as a broken website, and there is nothing here to reason about.

### Follow-up questions

`POST /api/predict/ask` takes a question and the exchange so far, and answers it about the
prediction on screen. The conversation lives in the browser — this service keeps no session, so two
people at the booth can never land in each other's thread, and a free-tier restart loses nothing.

**It is a second LLM mode, not a longer caption, and the difference is the whole point.** A judge
will ask, roughly in this order:

- *"So is this kid at risk?"* — a request for a **diagnosis**
- *"Should they cut out soda?"* — a request for **medical advice**
- *"Does sugar cause fatty liver?"* — a request for the **causal claim the study spent ten steps not
  making**

A prompt tuned for captioning would answer all three, helpfully and wrongly. So `/ask` gets its own
system prompt built around declining them and saying what the numbers *do* show. Both prompts share
`_study_facts()`, so they can never disagree about what the study found — only about what they are
allowed to do with it.

**The offline fallback does not answer.** This is the one place in the demo where the fallback
deliberately refuses to do what was asked. The caption's content is fully determined by the SHAP
contributions, so the server can generate it. An arbitrary question is not determined by anything
the server can compute, so the only honest options are to say the answer is unavailable or to make
one up — and a project whose entire argument is that it is careful about what it claims does not
get to make one up at the moment a judge is watching.

The starter questions are served from `/api/predict/questions`, not hard-coded in the frontend,
because they are part of the argument rather than decoration — one of them asks for a risk
assessment, and a judge watching the model *decline* learns more than a fluent answer would teach
them. Keeping them beside the prompt that has to handle them means the two get edited together.

Two smaller decisions: a follow-up gets ~2.5× the caption's timeout, because a caption loads on its
own when a slider moves and must not be noticed, while a question was typed and submitted by
someone already waiting on purpose. And the transcript is **cleared whenever an input moves** — an
answer about the previous adolescent sitting under a new chart is the one way this page could
actively mislead someone, and it is the obvious way to build it if nobody thinks about it.

The system prompt is **built from `engine.headline()` at call time**, not written by hand, so it
cannot come to disagree with the study it describes — the sugar null result and its *p*-value are
read from the same function the site's own summary card uses. The rules are mostly prohibitions:
no causal verbs, no medical advice, no facts that are not in the message.

The outbound call uses `urllib` from the standard library. One POST of a small JSON body with a
timeout is the whole requirement, and this service pays for every import on every cold start —
the same argument behind the frontend's hand-rolled ZIP and PDF writers.

### Configuring it

`OPENROUTER_API_KEY` is read **server-side only**, in `Backend/predict_api.py`, and never leaves
it. The browser calls this service; this service calls OpenRouter:

```
browser  →  Render (holds the key)  →  OpenRouter  →  Nemotron
```

Set it in the Render dashboard (`render.yaml` declares it `sync: false`, so the value is never in
the repo). Locally, export it in your shell. Then check:

```bash
curl https://<service>.onrender.com/api/predict/llm
```

**Leaving it unset is safe.** `/api/predict` never touches it, and `/api/predict/explain` falls
back to its generated text and says so. An unconfigured deploy is a working demo minus the
model-written paragraph, not a broken one.

Costs are negligible — ~600 tokens in and ~120 out per explanation, at $0.08/$0.20 per million for
Lightning. **Do not run the fair on the `:free` variants**: they are rate-limited per account, and
a night of testing followed by a queue of judges is exactly the traffic shape that trips them.

### The offline demo

```bash
uv run python scripts/build_offline_demo.py          # write offline/index.html
uv run python scripts/build_offline_demo.py --check  # CI's staleness guard
```

Hosting on Render makes a network connection a hard dependency of the *entire* demo, not just of
the language model — a captive portal on the venue wifi takes down the whole thing.
`offline/index.html` is one self-contained file with no server, no API, no fonts, no CDN and no
JavaScript library. Put it on a laptop or a USB stick and open it with a double click.

It cannot run the model, so six adolescents are run through the real engine at build time and their
predictions, SHAP breakdowns and fallback explanations are baked in. The page says so, in those
words, at the top.

### What a prediction is allowed to mean

Nothing here is a diagnosis and nothing here is causal. The model reports where NHANES adolescents
with a given set of numbers tended to sit, from one survey cycle and 586 participants. Moving an
input changes the model's guess; it does not tell you what would happen to a real person. Every
response carries that sentence, and the language model is handed it too.

Out-of-range inputs are **clamped and reported**, never silently accepted: a tree extrapolates by
returning its edge leaf, so a BMI of 90 produces the same answer as the highest BMI in the data,
and presenting that as a prediction about a BMI of 90 would be a lie the model cannot detect.

### Explaining it to a judge

> *"The prediction comes from a gradient boosting model we trained ourselves on the NHANES data —
> the same seven variables as our main regression. The chart underneath it is a SHAP decomposition:
> the model's starting point plus one bar per input equals the prediction exactly, so you can check
> the addition. The paragraph is written by NVIDIA's Nemotron through an API. We didn't train it —
> we send it our model's output and it puts it in plain English. It can't change the prediction."*

- *"Why an API instead of running it yourself?"* — A 550-billion-parameter model needs datacenter
  GPUs. Even the small one would add real complexity to a web deployment for no scientific benefit.
- *"Could the language model change the prediction?"* — No. It receives the prediction and the SHAP
  values as text and describes them. It has no access to the data or the model, and the page renders
  the numbers before it is asked.
- *"What if the AI is down?"* — The prediction and the chart don't depend on it. You'd get a
  paragraph the server writes from the same numbers, labelled as such. A follow-up question would
  say the model is unavailable rather than guess at an answer.
- *"Can it tell me if my kid is at risk?"* — No, and it's built to say so. Try asking it — that's
  one of the suggested questions.

## Development

```bash
uv run pytest                        # 118 Python tests
npm --prefix frontend test           # 49 frontend unit tests (vitest)
uv run python scripts/smoke_test.py  # 300 live HTTP checks
uv run ruff check Backend/ tests/ scripts/
uv run ruff format Backend/ tests/ scripts/
python Backend/engine.py build-cohort --check   # data/code drift guard
python Backend/engine.py train-model --check    # model/code drift guard
python scripts/build_offline_demo.py --check    # offline page staleness guard
```

The test suites are aimed at the failures that don't announce themselves. A statistics bug doesn't
raise — it returns a number that is wrong in a way no reader can see. So the tests check properties
rather than pinning values: that weights actually change the answer, that clusters nest PSU inside
stratum (clustering on the raw PSU column would collapse 30 clusters into 2 and silently undo the
correction), that compared models share a sample, that answer codes are decoded rather than
averaged, and that the caveats and claim grades are still attached.

`scripts/smoke_test.py` covers the gap the other two cannot. It boots uvicorn the way Render does
and sweeps every tier x column x group-by, every study step, every figure and lab endpoint, and
every client-side route -- 291 requests. Two things make it worth its runtime:

- **It reads response bodies, not just status codes.** The engine degrades rather than crashes: a
  block it cannot compute returns `{"error": ...}` inside a 200. A status-code check passes while
  the page shows "VIF computation failed", so the script walks each payload for a nested `error`.
- **It uses the deploy's import path.** pytest puts `Backend/` on `sys.path`; `uvicorn main:app`
  does not, so the two exercise different halves of every `try: import x / except: import
  Backend.x` pair in the codebase.

`frontend/src/lib/format.test.ts` covers the third gap: the rules that decide whether a
label-value pair fits in one grid cell. A wrong threshold there renders "0.5011" one digit per
line with no error anywhere in the stack.

## Deploying

`render.yaml` is a Render Blueprint. The build runs `npm ci && npm run build` first — if the
frontend fails, the deploy fails before touching Python and the previous version stays live — then
`pip install -r requirements.txt`. The start command is `uvicorn main:app`.

Two dependency manifests exist and can drift, so it's worth knowing which does what:

- **`requirements.txt`** hard-pins exact versions. **This is what Render builds from.**
- **`pyproject.toml` + `uv.lock`** drive local `uv sync`; `uv.lock` is the source of truth for the
  versions `uv` resolves.

Nothing regenerates one from the other, so bump both together.

`render.yaml` also declares the demo's environment: `OPENROUTER_API_KEY` as `sync: false` (Render
prompts for it; the value is never in the repo), plus the two model slugs and their timeouts as
plain values so a retired model can be swapped from the dashboard without a redeploy. See
[The language model](#the-language-model).

### Cold starts

Render's free plan spins the service down when idle. Two things keep the restart fast: pandas,
statsmodels and the engine are imported *lazily* inside the functions that use them, so uvicorn
binds the port and `/healthz` answers before any of that loads; and a background thread warms every
cache on startup — the dataframe, the column lists, the basic tier for each column, the figures,
and finally the study itself — so the first visitor usually finds the answers already computed.
`.github/workflows/keepalive.yml` pings `/healthz` on a schedule to keep the process resident —
but it needs a repo variable that is **currently unset**, so every scheduled run fails immediately:

```bash
gh variable set SERVICE_URL --body https://<service>.onrender.com
```

For a fair specifically, the pinger is second best. GitHub's cron is best-effort and routinely runs
late, which leaves a window wide enough for Render to spin the service down between judges. The
reliable fix is one line in `render.yaml` — `plan: starter` (~$7/month, always on) — for the month
of the fair, cancelled afterwards. Left on `free` in the repo because switching plans is a billing
decision, not a code one.

## Data sources

- [NHANES 2017–2018](https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/) — National Health and
  Nutrition Examination Survey (CDC/NCHS). Every coding decision in the cohort section is checked against
  the codebook PDFs in `extra_data/PDF_explanations/`.
- Schwimmer JB et al. (2010), *SAFETY study* — the sex-specific pediatric ALT thresholds; adopted
  in the NASPGHAN 2017 pediatric NAFLD screening guideline.
- `Data/data.csv` — small synthetic practice dataset, not wired into the running app.
- [laptopData.csv](https://www.kaggle.com/code/elhadjimouhamadou/laptop-prices-data-cleaning/input) — Kaggle data-cleaning dataset.
