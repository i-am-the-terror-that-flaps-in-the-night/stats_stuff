"""
Tests for the ALT predictor (Backend/engine.py part four) and the demo API
that serves it (Backend/predict_api.py).

WHAT THESE TESTS ARE GUARDING
    Two different kinds of thing can go wrong here, and they need different
    tests.

    The MODEL can become dishonest without becoming broken. A SHAP breakdown
    that does not add up to the prediction is a chart of plausible-looking bars
    that mean nothing, and it would render perfectly. A feature list that has
    drifted from the study's specification turns the "two estimators of one
    model" comparison into a comparison of two different models, and every
    number would still look fine. So the tests below pin the identities --
    additivity, the specification, determinism -- rather than the values, for
    the reason tests/test_study.py gives: asserting the coefficients only
    re-asserts whatever the code currently does.

    The DEMO can fail in front of a judge. Its whole design is that the
    prediction never depends on the network and the explanation never fails, so
    that is what is tested: the failover is driven through all three of its
    steps with the outbound call stubbed, and the canned step is required to
    produce real prose about the actual inputs.

    Nothing here calls OpenRouter. A test that needs an API key and a working
    connection is a test that is skipped in CI and therefore is not a test.

Run from the repo root with `uv run pytest`.
"""

import json

import numpy as np
import pytest

import engine
import predict_api
from engine import COHORT_CSV, PREDICTOR_CARD, PREDICTOR_TXT

pytestmark = pytest.mark.skipif(
    not (COHORT_CSV.is_file() and PREDICTOR_TXT.is_file() and PREDICTOR_CARD.is_file()),
    reason="cohort CSV or trained model not built",
)


@pytest.fixture(scope="module")
def card():
    return engine.predictor_card()


@pytest.fixture(scope="module")
def median_inputs(card):
    """The cohort's own median adolescent -- the form's default state."""
    return {name: spec["default"] for name, spec in card["inputs"].items()}


# ----------------------------------------------------------------------
# The specification: this model is the study's model, fitted differently
# ----------------------------------------------------------------------


def test_the_predictor_uses_the_protocols_primary_specification():
    """The whole claim of part four is that the tree model and the study's
    linear model are two estimators of ONE pre-specified specification. If the
    feature list drifts from MODEL_B_WITH_BMI that claim silently becomes
    false, and the out-of-fold comparison in the model card becomes a
    comparison of two different models presented as one."""
    assert engine.PREDICTOR_FEATURES == engine.MODEL_B_WITH_BMI


def test_the_committed_card_matches_the_specification_in_code(card):
    assert card["features"] == list(engine.PREDICTOR_FEATURES)
    assert set(card["inputs"]) == set(engine.PREDICTOR_FEATURES)


def test_every_feature_has_reader_facing_copy():
    """A feature with no label and no unit reaches the UI as a raw column name
    next to a bare number, which is the one thing this page cannot afford."""
    for name in engine.PREDICTOR_FEATURES:
        meta = engine.PREDICTOR_INPUTS[name]
        assert meta["label"] and meta["unit"] and meta["about"]


def test_the_model_was_trained_on_the_same_cohort_as_the_study(card):
    """n here must be the primary model's n, not some larger sample that quietly
    dropped a covariate to keep more rows."""
    assert card["n"] == engine.run_step("direct-effect")["n"]


# ----------------------------------------------------------------------
# The explanation: exact, not approximate
# ----------------------------------------------------------------------


def test_shap_contributions_sum_exactly_to_the_prediction(median_inputs):
    """TreeSHAP's defining property, and the reason the breakdown can be called
    a decomposition rather than an attribution heuristic. If this ever fails,
    the bars on the page are decoration."""
    result = engine.predict_alt(median_inputs)
    total = result["base_value_log"] + sum(
        driver["contribution_log"] for driver in result["drivers"]
    )
    assert total == pytest.approx(result["predicted_log_alt"], abs=1e-4)


def test_the_two_scales_agree(median_inputs):
    """The response reports ln(ALT) and U/L, and a reader will compare them.
    exp(log prediction) must be the U/L number, or the page contradicts itself."""
    result = engine.predict_alt(median_inputs)
    assert float(np.exp(result["predicted_log_alt"])) == pytest.approx(
        result["predicted_alt"], rel=1e-3
    )
    assert float(np.exp(result["base_value_log"])) == pytest.approx(
        result["baseline_alt"], rel=1e-3
    )


def test_drivers_are_ordered_by_how_much_they_moved_the_prediction(median_inputs):
    result = engine.predict_alt(median_inputs)
    sizes = [abs(driver["contribution_log"]) for driver in result["drivers"]]
    assert sizes == sorted(sizes, reverse=True)


def test_a_higher_bmi_raises_the_prediction(median_inputs):
    """A directional sanity check, and the only one in this file, because it is
    the one relationship the study, the literature and the model all agree on.
    A model that answered this backwards would be wired up wrong -- features
    swapped, say -- in a way no additivity check would catch."""
    lean = engine.predict_alt({**median_inputs, "BMI": 18.0})
    heavy = engine.predict_alt({**median_inputs, "BMI": 34.0})
    assert heavy["predicted_alt"] > lean["predicted_alt"]


def test_sugar_is_not_a_leading_driver(card):
    """The study's headline is that sugar does not independently predict ALT.
    The tree model reached the same place by a different route, and that
    agreement is quoted on the page and in the language model's system prompt.
    A retrain that promoted sugar to the top would make both of those false,
    and this test is where that would surface -- as a prompt to rewrite the
    claim, not as a licence to delete the test."""
    ranking = [row["feature"] for row in card["importance"]]
    assert ranking[0] in {"BMI", "Male"}
    assert ranking.index("Sugar10g") >= len(ranking) - 3


# ----------------------------------------------------------------------
# Inputs: clamped and reported, never silently invented
# ----------------------------------------------------------------------


def test_missing_inputs_fall_back_to_the_cohort_median_and_say_so(card):
    result = engine.predict_alt({"BMI": 25.0})
    assert result["adjustments"], "a half-filled form must report what was filled in"
    for name, spec in card["inputs"].items():
        if name != "BMI":
            assert result["inputs"][name] == spec["default"]


def test_out_of_range_inputs_are_clamped_and_reported(card):
    """A tree extrapolates by returning its edge leaf, so a BMI of 200 produces
    the same answer as the highest BMI in the cohort. Presenting that as a
    prediction about a BMI of 200 would be a lie the model cannot detect, so
    the clamp has to be announced."""
    ceiling = card["inputs"]["BMI"]["max"]
    result = engine.predict_alt({"BMI": 200.0})
    assert result["inputs"]["BMI"] == ceiling
    assert any("BMI" in note for note in result["adjustments"])


def test_slider_bounds_come_from_the_cohort(card):
    """Derived, not typed. Every default must sit inside its own range, and the
    range must bracket the median -- the failure this catches is a hand-edited
    bound that drifts from the data after a retrain."""
    for spec in card["inputs"].values():
        assert spec["min"] <= spec["default"] <= spec["max"]
        assert spec["min"] <= spec["cohort_median"] <= spec["max"]


def test_the_elevated_alt_line_is_sex_specific(median_inputs):
    boy = engine.predict_alt({**median_inputs, "Male": 1})
    girl = engine.predict_alt({**median_inputs, "Male": 0})
    assert boy["reference"]["elevated_threshold"] == engine.ALT_ELEVATED["Male"]
    assert girl["reference"]["elevated_threshold"] == engine.ALT_ELEVATED["Female"]


def test_predictions_carry_their_caveats(median_inputs):
    result = engine.predict_alt(median_inputs)
    assert result["not_causal"]
    assert "not a diagnosis" in result["caveat"]
    assert result["layer"] == engine.PREDICTIVE


# ----------------------------------------------------------------------
# The committed artifact
# ----------------------------------------------------------------------


def test_the_committed_model_passes_its_own_drift_check(card):
    """`train-model --check` is CI's guard against a model that no longer
    matches the cohort and code that produced it. Checked here against the
    committed pair itself, which must always be clean."""
    booster, _ = engine.load_predictor()
    assert engine._predictor_drift(booster, card) == []


@pytest.mark.parametrize(
    "field, value",
    [
        ("features", ["BMI"]),
        ("n", 1),
        ("rounds", 1),
        ("params", {}),
    ],
)
def test_the_drift_check_catches_a_changed_specification(card, field, value):
    """The failure this exists to prevent is silent: change a covariate or a
    hyperparameter, ship without retraining, and the site keeps explaining
    predictions from a model that no longer matches what the repo says it is.
    Every structural field must be load-bearing, not just listed."""
    booster, _ = engine.load_predictor()
    problems = engine._predictor_drift(booster, {**card, field: value})
    assert any(field in problem for problem in problems)


def test_the_drift_check_catches_a_reordered_importance_ranking(card):
    """ "BMI matters most, sugar barely matters" is a claim the page and the
    language model's prompt both make out loud. It has to be checked, not
    assumed to follow from the numbers being close."""
    booster, _ = engine.load_predictor()
    flipped = {**card, "importance": list(reversed(card["importance"]))}
    assert any("importance" in p for p in engine._predictor_drift(booster, flipped))


def test_the_card_is_json_and_reports_its_own_validation(card):
    json.dumps(card)  # raises if a numpy scalar leaked into the artifact
    scores = card["validation"]
    assert scores["clusters"] == 30
    assert scores["gradient_boosting"]["r_squared_log_alt"] is not None
    assert scores["linear_model_b_with_bmi"]["r_squared_log_alt"] is not None
    # Grouped by cluster, not by participant. Splitting two adolescents from one
    # sampled location across the train/test line inflates the score, and the
    # note beside the number is what tells a reader it was not done.
    assert "cluster" in scores["note"].lower()


# ----------------------------------------------------------------------
# The demo API and its failover
# ----------------------------------------------------------------------


def test_the_system_prompt_states_the_studys_null_result():
    """The one genuine risk in bolting a language model onto this project is
    that it says the thing the study spent ten steps not saying. The prompt is
    built from engine.headline() so it cannot drift from the result, and this
    test pins the parts a rewrite might drop."""
    prompt = predict_api._system_prompt()
    headline = engine.headline()

    assert str(headline["sugar_p"]) in prompt
    assert "does NOT" in prompt and "BMI" in prompt
    assert "Never use causal words" in prompt
    assert "medical advice" in prompt
    assert str(headline["n"]) in prompt


def test_the_canned_explanation_describes_the_actual_inputs(median_inputs):
    """Step three of the failover is generated prose, not a fixed paragraph --
    a static string would describe drivers the reader did not enter, and a judge
    who moves a slider and watches the words stay put learns something true and
    unflattering."""
    heavy = engine.predict_alt({**median_inputs, "BMI": 34.0})
    lean = engine.predict_alt({**median_inputs, "BMI": 18.0})

    heavy_text = predict_api._canned_explanation(heavy)
    lean_text = predict_api._canned_explanation(lean)

    assert heavy_text != lean_text
    assert str(heavy["predicted_alt"]) in heavy_text
    assert "not statements about any real person" in heavy_text


def test_the_explanation_falls_back_rather_than_failing(monkeypatch, median_inputs):
    """With no key configured -- CI, a dead venue wifi, a revoked credential --
    the route must still answer. This is the property the whole demo rests on."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    prediction = engine.predict_alt(median_inputs)

    answer = predict_api.explain_prediction(prediction)

    assert answer["source"] == "fallback"
    assert answer["explanation"]
    # Both models were tried and both recorded a reason, so a developer at the
    # booth can see WHY the fast one was skipped rather than guessing.
    assert len(answer["attempts"]) == 2
    assert all(not attempt["ok"] for attempt in answer["attempts"])


def test_the_second_model_is_tried_when_the_first_one_fails(monkeypatch, median_inputs):
    """Strategy B is a failover chain, not a quality router: any failure of the
    fast model -- timeout, HTTP error, a slug OpenRouter has retired -- must
    reach the slow one before the canned text."""
    calls = []

    def flaky(model, prompt, message, timeout):
        calls.append(model)
        if model == predict_api.PRIMARY_MODEL:
            raise TimeoutError("too slow")
        return "The model weighted body mass most heavily here."

    monkeypatch.setattr(predict_api, "_call_openrouter", flaky)
    answer = predict_api.explain_prediction(engine.predict_alt(median_inputs))

    assert calls == [predict_api.PRIMARY_MODEL, predict_api.FALLBACK_MODEL]
    assert answer["source"] == "llm"
    assert answer["model"] == predict_api.FALLBACK_MODEL
    assert answer["attempts"][0]["ok"] is False
    assert answer["attempts"][1]["ok"] is True


def test_a_working_primary_model_is_not_second_guessed(monkeypatch, median_inputs):
    monkeypatch.setattr(
        predict_api,
        "_call_openrouter",
        lambda model, prompt, message, timeout: "Body mass pushed it up.",
    )
    answer = predict_api.explain_prediction(engine.predict_alt(median_inputs))

    assert answer["source"] == "llm"
    assert answer["model"] == predict_api.PRIMARY_MODEL
    assert len(answer["attempts"]) == 1


class _FakeResponse:
    """The two things urlopen's context manager has to do for _call_openrouter."""

    def __init__(self, body: dict):
        self._payload = json.dumps(body).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        return False


def test_an_empty_llm_reply_counts_as_a_failure(monkeypatch):
    """A 200 carrying an empty message is the failure mode a status check waves
    through, and it renders as a blank explanation panel. _call_openrouter has
    one job -- return usable text or raise -- so a whitespace-only completion
    has to be the second of those, or the failover never fires."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(
        predict_api.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _FakeResponse(
            {"choices": [{"message": {"content": "   "}}]}
        ),
    )
    with pytest.raises(RuntimeError, match="empty"):
        predict_api._call_openrouter("m", "system", "user", timeout=1.0)


def test_a_usable_reply_is_returned_stripped(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(
        predict_api.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _FakeResponse(
            {"choices": [{"message": {"content": "  Body mass led.  "}}]}
        ),
    )
    assert predict_api._call_openrouter("m", "s", "u", timeout=1.0) == "Body mass led."


def test_a_missing_key_raises_before_any_network_call(monkeypatch):
    """No key must fail fast and locally. Sending an unauthenticated request and
    waiting out the timeout would spend the reader's three seconds proving
    something already knowable."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(
        predict_api.urllib.request,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("must not reach the network"),
    )
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        predict_api._call_openrouter("m", "s", "u", timeout=1.0)


def test_the_status_route_never_leaks_the_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-secret")
    status = predict_api.llm_status()

    assert status["configured"] is True
    assert "secret" not in json.dumps(status)


def test_the_status_route_reports_an_unset_key(monkeypatch):
    """The check to run against the deploy before the fair. If this says false
    on the day, every explanation will be the canned one."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert predict_api.llm_status()["configured"] is False
