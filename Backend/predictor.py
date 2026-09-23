"""
predictor.py -- the interactive demo's ALT predictor.

A gradient-boosted tree fitted on the same cohort and the same specification
as the study's primary model, so a visitor can put in one adolescent's
numbers and see a predicted ALT with a per-variable breakdown of how it got
there.

WHY A SECOND MODEL AT ALL, WHEN THE STUDY ALREADY HAS ONE
    Part three answers a hypothesis: does dietary sugar predict ALT once body
    mass and the metabolic markers are accounted for? That question needs a
    model whose coefficients are interpretable and whose standard errors
    respect the survey design, which is why it is weighted least squares and
    why it will stay that way.

    This part answers a different question -- given these seven numbers, what
    ALT would we guess, and which of the seven moved the guess? -- and it is
    the demo the poster stands next to. Gradient boosting is the better tool
    for that: it finds curvature and interactions the linear model cannot
    express, and out of fold it does measurably better (see CV_NOTE and the
    numbers in the committed model card).

    It is also a check on study.py rather than a replacement for it. The
    tree model is free to lean on whatever predicts ALT best, with no
    specification imposed and no linearity assumed. It leans on BMI and sex,
    then the metabolic markers, and it puts dietary sugar second from last.
    That is the study's null result arrived at a second way, by a method with
    no stake in it -- which is worth more than either result alone.

THE SPECIFICATION IS NOT CHOSEN HERE
    PREDICTOR_FEATURES is MODEL_B_WITH_BMI, the protocol's primary
    specification, in the protocol's units. Nothing was added because it
    helped and nothing was dropped because it did not, so the comparison above
    is between two estimators of one pre-specified model, not between two
    different models. A tree given a wider feature set would look better and
    would answer a question nobody asked.

THE EXPLANATION IS EXACT, AND IT IS NOT AN EXTRA DEPENDENCY
    Every prediction ships with per-feature SHAP contributions from
    LightGBM's own `pred_contrib=True`, which runs TreeSHAP inside the
    booster. These are the same numbers shap.TreeExplainer returns -- it
    delegates to this implementation for LightGBM models -- so the deployment
    plan's SHAP explainer is present in full, and the `shap` package is not.

    That matters here more than it usually would. `shap` pulls in
    scikit-learn, numba, llvmlite, cloudpickle, tqdm and slicer; this service
    runs on 512 MB of which imported libraries are already ~184 MB, and numba
    has no wheel for the Python version this project pins. LightGBM alone is
    a 3.5 MB wheel, adds ~10 MB resident on top of the stack this service
    already loads, and brings one pure-Python dependency (narwhals). Same
    numbers, none of the weight. See predict_alt().

    Contributions are additive by construction: base value + the seven
    contributions = the prediction, exactly, which is what makes the
    breakdown a decomposition rather than an attribution heuristic.
    tests/test_predictor.py pins that identity.

THE MODEL IS A COMMITTED ARTIFACT, NEVER TRAINED AT RUNTIME
    Same bargain as the cohort CSV in cohort.py, for the same reasons. The
    deploy has an ephemeral filesystem, so anything written at runtime is lost
    on the next restart, and a shared vCPU makes even this second of training
    something no visitor should wait for. So training happens on a developer's
    machine and its two outputs are committed:

        Backend/model/alt_lgbm.txt    the booster, LightGBM's own text format
        Backend/model/alt_lgbm.json   the model card -- features, units, the
                                      cross-validated scores, the input ranges
                                      the UI offers, and what it may claim

        python Backend/cli.py train-model          # retrain, write both
        python Backend/cli.py train-model --check  # retrain in memory, diff
                                            # against the committed pair

    --check is the same drift guard `build-cohort --check` is, and CI runs it
    for the same reason: a change to the cohort or to the feature list that
    ships without a retrain leaves the site explaining predictions from a
    model that no longer matches the data underneath it. Training is
    deterministic (fixed seed, `deterministic=True`, single-threaded, no
    bagging), so the check is a byte comparison and not an approximate one.

WHAT A PREDICTION IS ALLOWED TO MEAN
    Nothing here is a diagnosis and nothing here is causal. The model is
    fitted on 314 adolescents from one survey cycle; it reports where NHANES
    adolescents with a given set of numbers tended to sit, and it explains its
    own arithmetic. Moving a slider changes the model's guess, not anyone's
    liver. Every response carries PREDICTION_CAVEAT saying so, and the
    language model that narrates it is handed the same sentence.
"""

from __future__ import annotations

import argparse
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import lightgbm as lgb

# Two import paths because these modules are reached two ways: with Backend/ on
# sys.path (pytest, the `python Backend/cli.py` CLI) and with the repo root on
# it (`uvicorn main:app`, which imports Backend.app). Same idiom as app.py's
# _load_engine(). The dependency runs one way -- engine, cohort, study,
# predictor -- so none of these can close a cycle.
try:
    from engine import (
        NOT_CAUSAL,
        PREDICTIVE,
        _num,
    )
except ImportError:
    from Backend.engine import (
        NOT_CAUSAL,
        PREDICTIVE,
        _num,
    )

try:
    from cohort import (
        ALT_ELEVATED,
        ALT_THRESHOLD_SOURCE,
        ROOT,
    )
except ImportError:
    from Backend.cohort import (
        ALT_ELEVATED,
        ALT_THRESHOLD_SOURCE,
        ROOT,
    )

try:
    from study import (
        MODEL_B_COLUMNS,
        MODEL_B_WITH_BMI,
        _clusters,
        _percent_change,
        _wquantile,
        analysis_frame,
    )
except ImportError:
    from Backend.study import (
        MODEL_B_COLUMNS,
        MODEL_B_WITH_BMI,
        _clusters,
        _percent_change,
        _wquantile,
        analysis_frame,
    )


MODEL_DIR = Path(__file__).resolve().parent / "model"
PREDICTOR_TXT = MODEL_DIR / "alt_lgbm.txt"
PREDICTOR_CARD = MODEL_DIR / "alt_lgbm.json"

# LightGBM's Linux wheel links libgomp.so.1 (GNU OpenMP) but does not ship it,
# and Vercel's Python runtime does not install it, so the bare import raises
# OSError and every predict route 500s. A copy of the library is vendored in
# Backend/vendor/ (see its README); it is preloaded ONLY when the plain import
# fails for that reason, so macOS and any box with gcc's runtime never touch it.
VENDORED_LIBGOMP = Path(__file__).resolve().parent / "vendor" / "libgomp.so.1"


def _import_lightgbm():
    """`import lightgbm`, preloading the vendored libgomp if the runtime lacks it."""
    try:
        import lightgbm as lgb
    except OSError as err:
        if "libgomp" not in str(err):
            raise
        if not VENDORED_LIBGOMP.is_file():
            raise OSError(f"{err} (vendored copy absent at {VENDORED_LIBGOMP})") from err
        import ctypes

        ctypes.CDLL(str(VENDORED_LIBGOMP), mode=ctypes.RTLD_GLOBAL)
        import lightgbm as lgb
    return lgb

# The features, in the order the booster was trained on. This IS
# MODEL_B_WITH_BMI -- written as its own name because the booster's column order
# is part of the committed artifact and must not silently follow a change to the
# protocol list without a retrain. train_predictor() asserts they still match.
PREDICTOR_FEATURES = list(MODEL_B_WITH_BMI)

# Everything a reader needs to type one of these in, and everything the UI needs
# to offer it: what to call it, what it is measured in, and one plain sentence
# saying what it is. The slider bounds are NOT written here -- they are derived
# from the cohort at training time (see _input_spec), because a hand-typed range
# that drifts from the data would let a visitor ask the model about an
# adolescent unlike anyone it ever saw and get an answer with no warning on it.
PREDICTOR_INPUTS = {
    "Sugar10g": {
        "label": "Dietary sugar",
        "unit": "10 g/day",
        "about": (
            "Total sugars from the day-1 24-hour dietary recall. The model "
            "works in tens of grams, because that is the contrast the study "
            "reports; the control shows plain grams."
        ),
        "step": 0.5,
        # The one input whose model scale is not the scale a person thinks in.
        # The feature has to stay per-10 g -- it is what the booster was trained
        # on and what makes the contribution comparable to the study's
        # coefficient -- but "10, in tens of grams" is not a quantity a visitor
        # at a poster can picture, and "100 g/day" is. So the value crossing the
        # wire stays in model units and only its PRESENTATION is scaled.
        "display_factor": 10,
        "display_unit": "g/day",
    },
    "ScreenTime": {
        "label": "Screen time",
        "unit": "hours/day",
        "about": "Self-reported recreational screen time on a typical day.",
        "step": 0.5,
    },
    "Age": {
        "label": "Age",
        "unit": "years",
        "about": "Age at screening. The cohort is adolescents aged 12-17.",
        "step": 1,
    },
    "Male": {
        "label": "Sex",
        "unit": "0 = female, 1 = male",
        "about": (
            "Sex as recorded by NHANES. The strongest single predictor here "
            "after body mass: adolescent boys sit well above girls on ALT."
        ),
        "step": 1,
        "choices": [{"value": 0, "label": "Female"}, {"value": 1, "label": "Male"}],
    },
    "TrigHDLRatio": {
        "label": "Triglyceride / HDL ratio",
        "unit": "ratio",
        "about": (
            "Triglycerides divided by HDL cholesterol, both in mg/dL -- a "
            "standard marker of insulin resistance."
        ),
        "step": 0.1,
    },
    "HbA1c": {
        "label": "HbA1c",
        "unit": "%",
        "about": "Glycated haemoglobin: average blood sugar over ~3 months.",
        "step": 0.1,
    },
    "BMI": {
        "label": "BMI",
        "unit": "kg/m\u00b2",
        "about": (
            "Body mass index. Not age- and sex-standardized here, because the "
            "protocol's models use raw BMI and this model must match them."
        ),
        "step": 0.5,
    },
}

# Fixed and pre-specified, not tuned against the score. Shallow trees
# (num_leaves = 7), a floor of 25 observations per leaf and L2 shrinkage are
# what a 314-row sample can support; a deeper forest memorizes it. Determinism
# is not decoration either -- the committed booster is diffed byte for byte by
# `train-model --check`, so anything that varies run to run (bagging, thread
# scheduling, an unseeded RNG) would make that guard fire at random.
PREDICTOR_PARAMS = {
    "objective": "regression",
    "metric": "l2",
    "num_leaves": 7,
    "min_data_in_leaf": 25,
    "learning_rate": 0.05,
    "feature_fraction": 0.9,
    "lambda_l2": 1.0,
    "bagging_freq": 0,
    "verbosity": -1,
    "seed": 20260830,
    "deterministic": True,
    "force_row_wise": True,
    "num_threads": 1,
}

# The ceiling on boosting rounds the search may pick from. The chosen count
# lands in the forties on this cohort, so 300 is roomy enough not to be a
# binding constraint and small enough that a full nested cross-validation is a
# second of work rather than a minute.
PREDICTOR_MAX_ROUNDS = 300

PREDICTION_CAVEAT = (
    "This is a prediction, not a diagnosis and not a causal statement. The "
    "model reports where NHANES adolescents with these numbers tended to sit, "
    "from one survey cycle and 314 participants. Moving an input changes the "
    "model's guess; it does not tell you what would happen to a real person if "
    "that number changed."
)

CV_NOTE = (
    "Scores are out-of-fold, with the folds split by SAMPLING CLUSTER rather "
    "than by participant: two adolescents from the same sampled location are "
    "more alike than two strangers, so splitting them across the train/test "
    "line would let the model see its own answer and report a score it cannot "
    "reproduce. The number of boosting rounds is chosen INSIDE each training "
    "fold, by a second cross-validation that never touches the held-out "
    "cluster, so the reported score pays for that choice instead of hiding it. "
    "The linear figure beside it is the study's own primary specification "
    "(Model B with BMI) scored on exactly the same folds, which is what makes "
    "the two comparable."
)


# ----------------------------------------------------------------------
# TRAINING -- run from the CLI, never from a request
# ----------------------------------------------------------------------


def _cluster_folds(clusters, k: int, seed: int):
    """Assign whole sampling clusters to k folds.

    Grouped k-fold, hand-rolled, for the same reason the ZIP and PDF writers on
    the frontend are hand-rolled: sklearn's GroupKFold is 120 MB of dependency
    for twelve lines. Clusters are shuffled under a fixed seed and dealt round
    robin, which keeps the folds balanced without needing the group sizes.
    """
    unique = sorted(set(clusters))
    order = np.random.default_rng(seed).permutation(len(unique))
    assignment = {unique[i]: int(position % k) for position, i in enumerate(order)}
    return np.array([assignment[c] for c in clusters])


def _weighted_r2(actual, predicted, weights) -> float:
    """R-squared against a weighted mean, on the log scale the model fits."""
    actual, predicted = np.asarray(actual, float), np.asarray(predicted, float)
    weights = np.asarray(weights, float)
    mean = np.average(actual, weights=weights)
    residual = np.average((actual - predicted) ** 2, weights=weights)
    total = np.average((actual - mean) ** 2, weights=weights)
    return float("nan") if total == 0 else float(1 - residual / total)


def _fit_booster(features, outcome, weights, rounds: int) -> "lgb.Booster":
    """One booster on one sample. The single place lightgbm.train is called."""
    lgb = _import_lightgbm()

    dataset = lgb.Dataset(
        features,
        label=outcome,
        weight=weights,
        feature_name=list(PREDICTOR_FEATURES),
        params=PREDICTOR_PARAMS,
    )
    return lgb.train(PREDICTOR_PARAMS, dataset, num_boost_round=rounds)


def _choose_rounds(features, outcome, weights, clusters, seed: int) -> int:
    """How many boosting rounds this sample supports, by cross-validation.

    Fits k boosters and reads the whole learning curve out of each one in a
    single pass -- `num_iteration=i+1` predicts with a prefix of the trees, so
    300 candidate round counts cost one fit per fold rather than 300. The round
    count with the best out-of-fold R-squared wins.

    Called on the TRAINING part of an outer fold during scoring, and on the full
    cohort once for the model that actually ships. That is the distinction that
    keeps the published score honest: choosing the round count is part of
    fitting, so it has to happen inside the fold that is being scored.
    """
    fold = _cluster_folds(clusters, 4, seed)
    curve = np.zeros((len(outcome), PREDICTOR_MAX_ROUNDS))
    for held_out in range(4):
        train = fold != held_out
        test = fold == held_out
        booster = _fit_booster(
            features[train], outcome[train], weights[train], PREDICTOR_MAX_ROUNDS
        )
        for i in range(PREDICTOR_MAX_ROUNDS):
            curve[test, i] = np.asarray(
                booster.predict(features[test], num_iteration=i + 1), dtype=float
            )
    scores = [
        _weighted_r2(outcome, curve[:, i], weights) for i in range(PREDICTOR_MAX_ROUNDS)
    ]
    return int(np.argmax(scores)) + 1


def _cross_validate(features, outcome, weights, clusters, design) -> dict:
    """Score the tree model and the study's linear model on identical folds.

    Nested: the outer loop holds out clusters and scores, the inner loop (inside
    _choose_rounds) picks the round count using only the outer loop's training
    clusters. The linear comparison is refitted fold by fold too -- scoring a
    model that was fitted on all the data against folds of that same data would
    flatter it for free.
    """
    import statsmodels.api as sm

    outer = _cluster_folds(clusters, 5, 0)
    tree = np.zeros(len(outcome))
    linear = np.zeros(len(outcome))
    rounds_per_fold = []

    for held_out in range(5):
        train = outer != held_out
        test = outer == held_out
        rounds = _choose_rounds(
            features[train],
            outcome[train],
            weights[train],
            clusters[train],
            seed=1 + held_out,
        )
        rounds_per_fold.append(rounds)
        booster = _fit_booster(features[train], outcome[train], weights[train], rounds)
        tree[test] = np.asarray(booster.predict(features[test]), dtype=float)
        fit = sm.WLS(outcome[train], design[train], weights=weights[train]).fit()
        linear[test] = fit.predict(design[test])

    def mean_absolute_error(predicted) -> float:
        """Back on the U/L scale, where a reader can judge the size of a miss."""
        return float(
            np.average(np.abs(np.exp(outcome) - np.exp(predicted)), weights=weights)
        )

    return {
        "scheme": "5-fold, grouped by PSU within stratum, rounds chosen in an inner 4-fold",
        "folds": 5,
        "clusters": int(len(set(clusters))),
        "rounds_per_fold": rounds_per_fold,
        "gradient_boosting": {
            "r_squared_log_alt": _num(_weighted_r2(outcome, tree, weights), 4),
            "mean_absolute_error_u_per_l": _num(mean_absolute_error(tree), 2),
        },
        "linear_model_b_with_bmi": {
            "r_squared_log_alt": _num(_weighted_r2(outcome, linear, weights), 4),
            "mean_absolute_error_u_per_l": _num(mean_absolute_error(linear), 2),
        },
        "note": CV_NOTE,
    }


def _input_spec(frame) -> dict:
    """What the UI offers for each input: range, default, and the label copy.

    Bounds are the cohort's own 1st and 99th weighted percentiles, rounded
    outward, and the default is the weighted median. Deriving them rather than
    typing them is what keeps the sliders inside the data: the model has no way
    to signal that a BMI of 60 is outside everything it was fitted on, so the
    control does not offer one. The percentiles are weighted for the same reason
    every other number in this project is -- the sliders should describe U.S.
    adolescents, not this sample.
    """
    weights = frame["DietWeight"]
    spec = {}
    for name in PREDICTOR_FEATURES:
        values = frame[name]
        low = _wquantile(values, weights, 0.01)
        high = _wquantile(values, weights, 0.99)
        median = _wquantile(values, weights, 0.5)
        meta = PREDICTOR_INPUTS[name]
        step = meta["step"]
        spec[name] = {
            "name": name,
            "label": meta["label"],
            "unit": meta["unit"],
            "about": meta["about"],
            "min": _num(math.floor(low / step) * step, 3),
            "max": _num(math.ceil(high / step) * step, 3),
            "step": step,
            "default": _num(round(median / step) * step, 3),
            "cohort_median": _num(median, 3),
        }
        for optional in ("choices", "display_factor", "display_unit"):
            if optional in meta:
                spec[name] = {**spec[name], optional: meta[optional]}
    return spec


def train_predictor() -> tuple["lgb.Booster", dict]:
    """Fit the booster on the whole cohort and build its model card.

    Returns the trained booster and the card as a dict. Writing them is the
    CLI's job, not this function's, so `--check` can retrain in memory and
    compare without touching the repo.
    """
    if PREDICTOR_FEATURES != MODEL_B_WITH_BMI:
        # A guard, not a formality. This model exists to be the protocol's
        # specification fitted a second way; if the protocol gains a covariate
        # and this list does not, the comparison in _cross_validate quietly
        # stops being between two estimators of one model.
        raise ValueError(
            "PREDICTOR_FEATURES has drifted from MODEL_B_WITH_BMI: "
            f"{PREDICTOR_FEATURES} vs {MODEL_B_WITH_BMI}"
        )

    import statsmodels.api as sm

    frame = analysis_frame(MODEL_B_COLUMNS)
    features = frame[PREDICTOR_FEATURES].to_numpy(dtype=float)
    outcome = frame["LogALT"].to_numpy(dtype=float)
    weights = frame["DietWeight"].to_numpy(dtype=float)
    clusters = _clusters(frame).to_numpy()
    design = np.asarray(
        sm.add_constant(frame[MODEL_B_WITH_BMI].astype(float)), dtype=float
    )

    validation = _cross_validate(features, outcome, weights, clusters, design)
    rounds = _choose_rounds(features, outcome, weights, clusters, seed=99)
    booster = _fit_booster(features, outcome, weights, rounds)

    # Gain: the total improvement in squared error every split on a feature
    # bought, as a share of the whole forest's. Reported alongside the mean
    # absolute SHAP contribution because they answer different questions -- gain
    # is how much the model USED a feature while fitting, mean |SHAP| is how far
    # that feature actually moves a prediction. They agree here, which is worth
    # being able to see.
    gain = np.asarray(booster.feature_importance("gain"), dtype=float)
    total_gain = float(gain.sum())
    contributions = np.asarray(booster.predict(features, pred_contrib=True))
    mean_abs = np.average(np.abs(contributions[:, :-1]), axis=0, weights=weights)

    importance = [
        {
            "feature": name,
            "label": PREDICTOR_INPUTS[name]["label"],
            "gain_percent": _num(100 * gain[i] / total_gain, 2) if total_gain else None,
            "mean_abs_shap": _num(float(mean_abs[i]), 5),
        }
        for i, name in enumerate(PREDICTOR_FEATURES)
    ]
    importance.sort(key=lambda row: row["mean_abs_shap"] or 0, reverse=True)

    card = {
        "model": "LightGBM gradient-boosted trees",
        "outcome": "ln(ALT), U/L",
        "outcome_label": "Alanine aminotransferase (ALT)",
        "features": list(PREDICTOR_FEATURES),
        "specification": (
            "Model B with BMI -- the study's pre-specified primary "
            "specification, fitted here by gradient boosting instead of "
            "weighted least squares."
        ),
        "n": int(len(frame)),
        "clusters": int(len(set(clusters))),
        # Phrased as a sentence fragment, not a title, because the UI drops it
        # into running prose. A title-cased string there needs lower-casing to
        # fit, and lower-casing turns WTDRD1 into wtdrd1.
        "weighted": (
            "the day-1 dietary weight (WTDRD1), applied as a per-row training weight"
        ),
        "rounds": int(rounds),
        "params": dict(PREDICTOR_PARAMS),
        "base_value": _num(float(contributions[0, -1]), 5),
        "elevated_alt_thresholds": dict(ALT_ELEVATED),
        "elevated_alt_source": ALT_THRESHOLD_SOURCE,
        "validation": validation,
        "importance": importance,
        "inputs": _input_spec(frame),
        "trained_on": "NHANES 2017-2018, adolescents aged 12-17",
        "caveat": PREDICTION_CAVEAT,
        "not_causal": NOT_CAUSAL,
    }
    return booster, card


def _predictor_drift(fresh_booster, fresh_card: dict) -> list[str]:
    """What differs between a fresh training run and the committed model.

    WHY THIS IS NOT A BYTE COMPARISON
        Training is deterministic -- fixed seed, `deterministic=True`, one
        thread, no bagging -- so on one machine a retrain reproduces the
        committed file exactly, and comparing bytes was the obvious check to
        write. It is the wrong one, because the model is trained on a developer's
        Mac and verified in CI on x86 Linux, and nothing in LightGBM's contract
        promises bit-identical split thresholds across architectures. A guard
        that can fail for a last-digit difference in a threshold is a guard that
        goes red on a repository where nothing is wrong, and a CI check nobody
        trusts is worse than none.

        So this compares the two things a byte comparison was standing in for:

          STRUCTURE, exactly. The feature list, the sample, the cluster count,
          the chosen round count, every hyperparameter, and the input ranges the
          UI offers. Every drift this guard exists to catch -- a changed
          inclusion rule, a covariate added to the protocol, a hyperparameter
          edited and not retrained -- moves at least one of these, and none of
          them is a float that platform noise can nudge.

          BEHAVIOUR, to a tolerance far tighter than any real drift. The two
          boosters must predict the same ALT for all 314 adolescents to within
          1e-6 on the log scale. A model that agrees to six decimals on every
          row of its own training set IS the committed model; a model refitted
          on a cohort that moved does not come close.
    """
    if not PREDICTOR_TXT.is_file() or not PREDICTOR_CARD.is_file():
        return ["Backend/model/ is missing or incomplete -- run train-model"]

    lgb = _import_lightgbm()

    committed_card = json.loads(PREDICTOR_CARD.read_text())
    committed_booster = lgb.Booster(model_str=PREDICTOR_TXT.read_text())
    problems = []

    for field in ("features", "n", "clusters", "rounds", "params", "inputs"):
        if committed_card.get(field) != fresh_card.get(field):
            problems.append(
                f"{field}: committed {committed_card.get(field)!r} != "
                f"fresh {fresh_card.get(field)!r}"
            )

    # The ranking, not the values behind it. Which input matters most is a claim
    # the site and the language model's prompt both make out loud; the fifth
    # decimal of a mean |SHAP| is not.
    def ranking(card: dict) -> list:
        return [row["feature"] for row in card["importance"]]

    if ranking(committed_card) != ranking(fresh_card):
        problems.append(
            f"importance order: committed {ranking(committed_card)} != "
            f"fresh {ranking(fresh_card)}"
        )

    frame = analysis_frame(MODEL_B_COLUMNS)
    features = frame[PREDICTOR_FEATURES].to_numpy(dtype=float)
    gap = float(
        np.max(
            np.abs(
                committed_booster.predict(features) - fresh_booster.predict(features)
            )
        )
    )
    if gap > 1e-6:
        problems.append(
            f"predictions: the committed model and a fresh one differ by up to "
            f"{gap:.3g} in ln(ALT) across the cohort"
        )
    return problems


def train_predictor_cli(argv=None) -> int:
    """`train-model` and `train-model --check`.

    Writes the booster and its card, or -- with --check -- retrains in memory
    and compares against the committed pair without touching them. See
    _predictor_drift() for what "compares" means and why it is not a diff.
    """
    parser = argparse.ArgumentParser(
        prog="engine.py train-model",
        description="Fit the ALT predictor and write Backend/model/.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Retrain in memory and compare with the committed model; write nothing.",
    )
    args = parser.parse_args(list(argv or []))

    booster, card = train_predictor()
    booster_text = booster.model_to_string()
    card_text = json.dumps(card, indent=2, default=str) + "\n"

    if args.check:
        problems = _predictor_drift(booster, card)
        if problems:
            print("Committed model is stale:")
            for problem in problems:
                print(f"  - {problem}")
            print("Fix with: python Backend/cli.py train-model")
            return 1
        print(
            f"Committed model matches its derivation "
            f"(n = {card['n']}, {card['rounds']} rounds)."
        )
        return 0

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    PREDICTOR_TXT.write_text(booster_text)
    PREDICTOR_CARD.write_text(card_text)

    scores = card["validation"]
    print(f"Trained on n = {card['n']} across {card['clusters']} clusters.")
    print(f"  rounds                {card['rounds']}")
    print(
        "  out-of-fold R^2       "
        f"{scores['gradient_boosting']['r_squared_log_alt']} (trees) vs "
        f"{scores['linear_model_b_with_bmi']['r_squared_log_alt']} (Model B linear)"
    )
    print("  drivers, by mean |SHAP|:")
    for row in card["importance"]:
        print(f"    {row['label']:<28} {row['mean_abs_shap']}")
    print(
        f"Wrote {PREDICTOR_TXT.relative_to(ROOT)} and {PREDICTOR_CARD.relative_to(ROOT)}."
    )
    return 0


# ----------------------------------------------------------------------
# SERVING -- what a request actually calls
# ----------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_predictor() -> tuple["lgb.Booster", dict]:
    """The committed booster and its card, read once per process.

    Reads the artifact; never trains. A missing artifact raises rather than
    falling back to training, because the fallback would be a minute of a tenth
    of a vCPU inside somebody's request and would then be thrown away on the
    next restart. predict_api.py turns the error into a clean 503.
    """
    lgb = _import_lightgbm()

    if not PREDICTOR_TXT.is_file() or not PREDICTOR_CARD.is_file():
        raise FileNotFoundError(
            "No trained model in Backend/model/. "
            "Build it with: python Backend/cli.py train-model"
        )
    booster = lgb.Booster(model_str=PREDICTOR_TXT.read_text())
    return booster, json.loads(PREDICTOR_CARD.read_text())


def predictor_card() -> dict:
    """The model card the UI builds its form and its disclosures from."""
    return load_predictor()[1]


def _clamp_inputs(values: dict, card: dict) -> tuple[list[float], list[str]]:
    """Put the seven inputs in the booster's order, inside the cohort's range.

    Out-of-range values are clamped and REPORTED, not rejected. A tree model
    extrapolates by returning the edge leaf, so a BMI of 90 silently produces
    the same answer as the highest BMI in the data -- clamping makes that
    explicit instead of letting the UI present an invented prediction as a real
    one. The returned notes travel all the way to the response and to the
    language model's prompt.
    """
    spec = card["inputs"]
    ordered, notes = [], []
    for name in card["features"]:
        bounds = spec[name]
        given = values.get(name)
        if given is None:
            given = bounds["default"]
            notes.append(f"{bounds['label']} was not given; used the cohort median.")
        number = float(given)
        if not math.isfinite(number):
            raise ValueError(f"{bounds['label']} must be a finite number.")
        low, high = float(bounds["min"]), float(bounds["max"])
        if number < low or number > high:
            notes.append(
                f"{bounds['label']} was {_num(number, 3)}, outside the cohort's "
                f"{low}-{high} {bounds['unit']}; clamped to the edge, where the "
                "model has data."
            )
            number = min(max(number, low), high)
        ordered.append(number)
    return ordered, notes


def _display_value(number: float, spec: dict) -> str:
    """One input's value as a reader would say it aloud.

    Three cases: a choice reads as its own name, a scaled input reads in the
    unit a person thinks in (see Sugar10g's display_factor), and everything else
    reads as itself.
    """
    for choice in spec.get("choices", ()):
        if float(choice["value"]) == number:
            return str(choice["label"])
    factor = float(spec.get("display_factor", 1))
    unit = spec.get("display_unit", spec["unit"])
    return f"{_num(number * factor, 3)} {unit}"


def predict_alt(values: dict) -> dict:
    """One prediction, with its exact SHAP decomposition.

    `pred_contrib=True` runs TreeSHAP in the booster and returns one column per
    feature plus a final base-value column, and those sum to the prediction
    exactly. So the breakdown below is arithmetic on the model's own output --
    "sex added 0.06 to ln(ALT)" is a statement about this forest, checkable by
    addition, not an approximation of one.

    Everything is reported on both scales. The model works in ln(ALT), which is
    where the contributions are additive and comparable; a reader wants U/L,
    which is where they are multiplicative. Giving one without the other invites
    somebody to add up percentages that do not add up.
    """
    booster, card = load_predictor()
    ordered, notes = _clamp_inputs(values, card)

    row = np.asarray([ordered], dtype=float)
    contributions = np.asarray(booster.predict(row, pred_contrib=True))[0]
    base = float(contributions[-1])
    log_prediction = float(base + contributions[:-1].sum())
    prediction = float(np.exp(log_prediction))

    spec = card["inputs"]
    drivers = []
    for i, name in enumerate(card["features"]):
        effect = float(contributions[i])
        drivers.append(
            {
                "feature": name,
                "label": spec[name]["label"],
                "value": _num(ordered[i], 3),
                "unit": spec[name]["unit"],
                # The same value as a person would say it. For a choice input
                # that is the choice's name -- "Male", not "1 0 = female,
                # 1 = male", which is what pasting the raw value next to the
                # unit produces. Built here rather than in the UI because three
                # consumers need it and they must agree: the table, the chart's
                # tooltip, and the text handed to the language model, which
                # would otherwise be asked to narrate a coded number.
                "display": _display_value(ordered[i], spec[name]),
                "cohort_median": spec[name]["cohort_median"],
                # The median in the same units the entered value is shown in,
                # or None for a choice input -- the median of a 0/1 column is a
                # real number and a meaningless one to print next to "Male".
                # Without this the sugar row read "entered 140 g/day (cohort
                # median 9.963)", two scales in one sentence.
                "cohort_median_display": (
                    None
                    if spec[name].get("choices")
                    else _display_value(spec[name]["cohort_median"], spec[name])
                ),
                # The contribution to ln(ALT), which is the additive one...
                "contribution_log": _num(effect, 5),
                # ...and the same thing as a multiplier on ALT, which is what it
                # means in U/L. exp(b) - 1, for the reason _percent_change gives.
                "percent_of_alt": _percent_change(effect),
                "direction": "raises"
                if effect > 0
                else "lowers"
                if effect < 0
                else "neutral",
            }
        )
    drivers.sort(key=lambda d: abs(d["contribution_log"] or 0), reverse=True)

    # The elevated-ALT line is sex-specific (see ALT_ELEVATED), and sex is one
    # of the inputs, so the right threshold is known here. This is a comparison
    # against a published cutoff, not a classification: the model predicts a
    # central value, and half of any real group sits above its own prediction.
    is_male = bool(ordered[card["features"].index("Male")] >= 0.5)
    threshold = ALT_ELEVATED["Male" if is_male else "Female"]

    return {
        "predicted_alt": _num(prediction, 2),
        "predicted_log_alt": _num(log_prediction, 5),
        "base_value_log": _num(base, 5),
        "baseline_alt": _num(float(np.exp(base)), 2),
        "units": "U/L",
        "inputs": {
            name: _num(ordered[i], 3) for i, name in enumerate(card["features"])
        },
        "drivers": drivers,
        "reference": {
            "elevated_threshold": threshold,
            "sex": "male" if is_male else "female",
            "above_threshold": bool(prediction >= threshold),
            "means": (
                f"The predicted value is {'at or above' if prediction >= threshold else 'below'} "
                f"the {threshold} U/L line this project uses for "
                f"{'boys' if is_male else 'girls'}. That line describes a "
                "population, and one prediction sitting near it is not a finding "
                "about a person."
            ),
        },
        "adjustments": notes,
        "layer": PREDICTIVE,
        "caveat": PREDICTION_CAVEAT,
        "not_causal": NOT_CAUSAL,
    }
