// The glossary: every term the site prints that a reader might not know,
// explained in one or two plain sentences.
//
// One file, three consumers. <Term> wraps any label that has an entry here so
// hovering (or tapping) it shows the definition in place; Docs renders the whole
// list as a reference; and the Overview's column/tier hints read from the same
// map. Keeping it in one place is what stops the hover text on a stat cell from
// drifting away from the definition in the docs.
//
// Keys are matched loosely -- see `lookup` -- so "r_squared", "R²" and
// "R-squared" all land on the same entry.

export interface GlossaryEntry {
  /** The word as it should print in a heading. */
  term: string;
  /** Plain-language definition. Two sentences at most. */
  def: string;
  /** Which section of the Docs glossary it belongs in. */
  group: "statistics" | "study" | "variables";
  /** Extra spellings the site uses for the same thing. */
  aliases?: string[];
  /** For variables: the unit, or the coding. */
  unit?: string;
}

export const GLOSSARY: GlossaryEntry[] = [
  // ---- statistics ---------------------------------------------------------
  { group: "statistics", term: "n", aliases: ["count", "n_obs"], def: "How many people (or values) went into this number. Every statistic is only as trustworthy as its n." },
  { group: "statistics", term: "mean", aliases: ["weighted mean", "weighted_mean", "unweighted_mean", "mean_alt", "weighted_mean_alt", "weighted mean sugar g", "weighted_mean_sugar_g"], def: "The ordinary average: add everything up and divide by n. One extreme value can pull it a long way." },
  { group: "statistics", term: "median", aliases: ["weighted_median", "weighted_median_alt", "50th percentile"], def: "The middle value once everything is sorted — half the people are below it, half above. Unlike the mean it ignores extreme values, which is why it is the better 'typical' for a skewed measure like ALT." },
  { group: "statistics", term: "mode", def: "The value that appears most often. Ties are all reported." },
  { group: "statistics", term: "min / max", aliases: ["min", "max"], def: "The smallest and largest values actually observed." },
  { group: "statistics", term: "standard deviation", aliases: ["std", "sd", "weighted_sd", "weighted sd"], def: "How spread out the values are: the typical distance from the mean, in the same units as the data. About two-thirds of values fall within one SD of the mean if the distribution is roughly bell-shaped." },
  { group: "statistics", term: "variance", def: "The standard deviation squared. Same idea (spread), harder to read because its units are squared." },
  { group: "statistics", term: "standard error", aliases: ["se", "std_error", "standard_error", "standard_error_alt", "standard_error_mean_alt"], def: "How uncertain an estimate is — how much the mean (or a coefficient) would wobble if the study were repeated. Smaller with bigger n. Not the same as standard deviation, which describes the people, not the estimate." },
  { group: "statistics", term: "confidence interval", aliases: ["95% ci", "ci", "ci_low", "ci_high", "ci lower", "ci upper", "interval"], def: "The range of values compatible with the data. If the 95% interval for a coefficient includes zero, the data cannot tell that effect apart from no effect." },
  { group: "statistics", term: "p-value", aliases: ["p", "p_value", "p value", "p_values", "p_value_means"], def: "The chance of seeing a result at least this extreme if there were truly no effect. Small (below 0.05) means the pattern is hard to explain by sampling noise alone. It is NOT the probability the finding is true, and it says nothing about how big the effect is." },
  { group: "statistics", term: "alpha", def: "The cutoff used to call a p-value 'significant'. This study uses 0.05, the convention." },
  { group: "statistics", term: "statistically significant", aliases: ["statistically_significant", "significant"], def: "p below 0.05: the data are unlikely under 'no effect'. It does not mean the effect is large or important — read the effect size beside it." },
  { group: "statistics", term: "effect size", aliases: ["effect_size", "magnitude"], def: "How big a difference or relationship is, separate from whether it is 'significant'. A tiny effect can be significant in a big sample; that is why every test here reports both." },
  { group: "statistics", term: "estimate", aliases: ["coefficient", "coefficients", "coefficients_mean"], def: "In a regression table, the change in the outcome for a one-unit rise in that predictor, with the other predictors held fixed. Here the outcome is ln(ALT), so 0.03 means roughly a 3% higher ALT per unit." },
  { group: "statistics", term: "standardized beta", aliases: ["β", "beta", "standardized_beta", "standardized_betas", "std beta"], def: "The coefficient rescaled so every predictor is in standard-deviation units. It answers 'which predictor matters most?' — a β of 0.42 (BMI) is about three times the pull of 0.13 (Trig/HDL)." },
  { group: "statistics", term: "R²", aliases: ["r_squared", "r squared", "r-squared", "adj_r_squared", "adjusted_r_squared", "adjusted r²", "delta_r_squared", "delta r squared", "delta_r_squared_with_bmi"], def: "The share of the outcome's variation the model explains, from 0 to 1. R² = 0.30 means the predictors together account for 30% of why ALT differs between adolescents; the other 70% is things not in the model." },
  { group: "statistics", term: "Pearson r", aliases: ["r", "correlation", "correlations", "pearson"], def: "How closely two columns move together in a straight line, from −1 to +1. 0 is no linear relationship; the sign says whether one rises as the other rises (+) or falls (−)." },
  { group: "statistics", term: "regression", aliases: ["ols", "wls", "model", "predictors", "outcome"], def: "Fitting a line (or plane) through the data to estimate how each predictor relates to the outcome while holding the others constant. WLS is the same thing with survey weights so the fit describes U.S. adolescents." },
  { group: "statistics", term: "residual", aliases: ["residuals", "large_residuals", "mean_residual", "diagnostics"], def: "The gap between what the model predicted for a person and what was actually measured. Residuals that fan out or curve mean the model is missing something." },
  { group: "statistics", term: "skewness", def: "Whether the distribution has a long tail on one side. Positive = a tail of high values (ALT is strongly right-skewed: most adolescents low, a few very high). 0 is symmetric." },
  { group: "statistics", term: "kurtosis", aliases: ["kurtosis_excess"], def: "How heavy the tails are compared with a bell curve. High kurtosis means more extreme values than a normal distribution would give." },
  { group: "statistics", term: "normality", aliases: ["detectably_non_normal", "shapiro_p", "normal"], def: "Whether the values follow a bell curve. Many tests assume they roughly do, which is why ALT is analysed on the log scale — the raw values are far from normal." },
  { group: "statistics", term: "log transform", aliases: ["ln(alt)", "logalt", "log", "natural log", "transformation_applied"], def: "Modelling the natural logarithm of ALT instead of ALT itself. It pulls the long right tail in so the regression assumptions hold. Coefficients then read as percentage changes: a coefficient of 0.03 ≈ 3% higher ALT." },
  { group: "statistics", term: "VIF", aliases: ["vif", "multicollinearity", "high_multicollinearity"], def: "Variance inflation factor: how much two predictors overlap. Above 5 they are so similar the model cannot tell their effects apart. The largest here is 1.28, so no problem." },
  { group: "statistics", term: "quartile", aliases: ["quartiles", "q1", "q2", "q3", "q4"], def: "One quarter of the sample, after sorting by sugar intake. Q1 is the lowest-sugar quarter, Q4 the highest." },
  { group: "statistics", term: "ANOVA", aliases: ["anova", "f_statistic"], def: "One test of whether several group means (here the four sugar quartiles) differ at all. F near 1 and a large p means they do not." },
  { group: "statistics", term: "chi-square", aliases: ["chi_square", "chi square", "contingency", "table"], def: "A test of whether a proportion (here % with elevated ALT) differs between groups. Works on counts, not means." },
  { group: "statistics", term: "trend test", aliases: ["trend_test", "cochran-armitage", "cochran armitage", "trend"], def: "Asks whether something rises (or falls) in order across ordered groups — e.g. does ALT climb step by step from quartile 1 to 4? One coefficient answers that instead of many pairwise comparisons." },
  { group: "statistics", term: "dose-response", aliases: ["dose response"], def: "More of the exposure → more of the outcome, in order. Finding one is a strong hint an association is real; this study finds none for sugar." },
  { group: "statistics", term: "degrees of freedom", aliases: ["df", "degrees_of_freedom"], def: "Roughly how many independent pieces of information a test has to work with. Reported alongside the test statistic; you rarely need to interpret it." },
  { group: "statistics", term: "test statistic", aliases: ["statistic", "t", "z", "test"], def: "The number a test computes before converting it to a p-value (t, z, F or chi-square). Bigger in magnitude = further from 'no effect'." },
  { group: "statistics", term: "weighted", aliases: ["weight", "survey weight", "weighting", "wtdrd1"], def: "Each adolescent counts in proportion to how many U.S. adolescents they represent, so results describe the country rather than whoever NHANES happened to recruit." },
  { group: "statistics", term: "clusters", aliases: ["cluster", "psu", "primary sampling unit"], def: "NHANES samples whole neighbourhoods, not individuals. The cluster count (30) is how many of those groups the sample came from; the classical standard errors used here do not adjust for it, so borderline p-values are approximate." },
  { group: "statistics", term: "cross-sectional", def: "Everything was measured at one visit. It can show what goes together, never what causes what." },
  { group: "statistics", term: "mediation", aliases: ["decomposition", "indirect", "direct effect", "total effect", "proportion_mediated", "attenuation_percent"], def: "Splitting sugar's link to ALT into the part that travels through BMI (indirect) and the part that does not (direct). Comparing Model B with and without BMI is how that split is estimated." },
  { group: "statistics", term: "layer", aliases: ["claim layer"], def: "How strong a claim a result supports: descriptive (what the data look like), inferential (what they suggest about the population), predictive (how well one thing predicts another). Never causal." },
  { group: "statistics", term: "IQR", aliases: ["iqr", "interquartile range"], def: "The middle 50% of values (75th percentile minus 25th). Used by the outlier rule: anything more than 1.5 × IQR beyond the box is flagged." },
  { group: "statistics", term: "at or above", aliases: ["at_or_above", "proportion_at_or_above", "below", "clinical_threshold"], def: "The share of the sample at or past a published cutoff — for ALT, the pediatric thresholds of 22 U/L (girls) and 26 U/L (boys)." },
  { group: "statistics", term: "ECDF", aliases: ["cumulative share", "cumulative"], def: "The cumulative curve: for any value on the x-axis, the height is the share of people at or below it. Read percentiles straight off it." },
  { group: "statistics", term: "Q-Q plot", aliases: ["q-q", "qq"], def: "Data quantiles plotted against what a normal distribution would give. Points on the diagonal = normal; a curve away from it = skew." },
  { group: "statistics", term: "density", aliases: ["kde", "bandwidth"], def: "A smoothed histogram. Bandwidth is how much smoothing; wider hides bumps, narrower shows noise." },
  { group: "statistics", term: "bootstrap", def: "Resampling the data many times with replacement to see how much an estimate wobbles. A way to get uncertainty without assuming a bell curve." },

  // ---- study design -------------------------------------------------------
  { group: "study", term: "NHANES", aliases: ["nhanes 2017–2018", "nhanes 17–18"], def: "The National Health and Nutrition Examination Survey, run by the CDC. It interviews, examines and takes blood from a sample chosen to represent the whole U.S. population. This study uses the 2017–2018 cycle." },
  { group: "study", term: "Model A", aliases: ["lifestyle model", "lifestyle_model", "lifestyle_model_full_sample"], def: "The lifestyle-only regression: ln(ALT) on sugar, screen time, age and sex. Runs on all 695 adolescents." },
  { group: "study", term: "Model B", aliases: ["combined model", "combined_model", "combined_model_with_bmi", "full model", "total_model", "direct_model"], def: "Model A plus the two metabolic markers, the Trig/HDL ratio and HbA1c. Fitted twice — without BMI (sugar's total link to ALT) and with BMI (its direct link). It needs fasting blood, so n = 314." },
  { group: "study", term: "primary test", aliases: ["primary", "primary_test", "pre-specified"], def: "The one test the study was designed to answer, chosen before looking at the data: is sugar's coefficient in Model B with BMI different from zero? It is not (p = 0.30)." },
  { group: "study", term: "supporting", def: "A pre-planned analysis that backs up or qualifies the primary test — dose-response, R² comparison, the descriptive profile." },
  { group: "study", term: "exploratory", def: "Looked at after the main question, without correction for multiple testing. Interesting, but it needs its own study to confirm — the sex split and the risk score." },
  { group: "study", term: "elevated ALT", aliases: ["altelevated", "alt elevated", "elevated_alt", "percent_elevated_alt", "percent elevated", "% elevated", "percent_elevated_alt_unweighted", "count_elevated"], def: "ALT above the pediatric screening cutoff: more than 26 U/L for boys, more than 22 U/L for girls (Schwimmer 2010, adopted by NASPGHAN 2017). About 10.5% of U.S. adolescents are above it." }, 
  { group: "study", term: "fasting subsample", aliases: ["fasting", "fasting_subsample_n"], def: "NHANES only measures triglycerides on the morning participants who fasted overnight. That is why anything using the Trig/HDL ratio has n = 314 instead of 695." },
  { group: "study", term: "attrition", aliases: ["cohort", "removed", "remaining"], def: "Who was dropped and why on the way from all 9,254 NHANES participants to the 695 adolescents analysed: age 12–17, a reliable diet recall, no hepatitis B or C, and complete data." },
  { group: "study", term: "risk score", aliases: ["riskscore", "risk_score", "score", "bands", "composite risk score"], def: "0–6 points: one for each of sugar, screen time, Trig/HDL, HbA1c and BMI above this cohort's median, plus one for being male. Mean ALT rises about 13.7% per point — but the cutoffs are this sample's own medians, so it ranks these adolescents against each other rather than being a clinical tool." },
  { group: "study", term: "classical standard errors", aliases: ["classical", "wls · classical", "estimator"], def: "The textbook standard errors from a weighted least-squares fit — what the written protocol specifies. They do not adjust for NHANES' clustered sampling, so p-values near 0.05 are approximate." },
  { group: "study", term: "interaction", aliases: ["interaction_model", "interaction_tests", "sugarxmale", "ratioxmale", "slopes_differ_by_sex"], def: "A term testing whether a predictor's slope differs between groups — e.g. does the Trig/HDL slope differ for boys and girls? (It does, p = 0.04; the sugar slope does not.)" },
  { group: "study", term: "tier", aliases: ["basic", "medium", "advanced", "expert", "categorical"], def: "How deep the engine goes on a column: basic (centre and spread) → medium (shape, interval, group tests) → advanced (correlation, regression) → expert (diagnostics, thresholds, trend). Categorical is for label columns." },

  // ---- variables ----------------------------------------------------------
  { group: "variables", term: "ALT", unit: "U/L", aliases: ["alanine aminotransferase", "logalt"], def: "Alanine aminotransferase, a liver enzyme measured in blood. It leaks out when liver cells are stressed or damaged, so higher ALT is the standard early marker of fatty-liver disease. This is the study's outcome." },
  { group: "variables", term: "Total sugars", unit: "g/day", aliases: ["totalsugars", "total sugars", "sugar10g", "sugar", "totalsugarsday2", "totalsugars2day", "total sugars day2", "total sugars2 day"], def: "Grams of sugar eaten on the recall day, from the NHANES 24-hour dietary interview. Regressions use it per 10 g so the coefficient is readable. Day 2 is the second recall; '2-day' is the average of both." },
  { group: "variables", term: "BMI", unit: "kg/m²", def: "Body-mass index, weight divided by height squared. The single strongest predictor of ALT in this study (β = 0.42)." },
  { group: "variables", term: "Triglycerides", unit: "mg/dL", aliases: ["trig", "lbxtr"], def: "A blood fat measured after fasting. High values go with insulin resistance and fat build-up in the liver." },
  { group: "variables", term: "HDL cholesterol", unit: "mg/dL", aliases: ["hdlcholesterol", "hdl"], def: "The 'good' cholesterol. Low HDL, like high triglycerides, is a sign of metabolic strain." },
  { group: "variables", term: "Trig/HDL ratio", unit: "ratio", aliases: ["trighdlratio", "trig hdl ratio", "trig_hdl_ratio", "trig/hdl", "triglyceride/hdl ratio", "ratios"], def: "Triglycerides divided by HDL — a simple marker of insulin resistance. It stays a significant predictor of ALT even with BMI in the model (β = 0.13, p = 0.016), which sugar does not." },
  { group: "variables", term: "HbA1c", unit: "%", aliases: ["hba1c", "glycohemoglobin", "a1c"], def: "Glycated haemoglobin: average blood sugar over the past ~3 months. 5.7% and above is pre-diabetic in adults, but almost no adolescent reaches that, so the risk score cuts it at the sample median (5.3%)." },
  { group: "variables", term: "Screen time", unit: "hours/day (0–5 as is, 8 = 8+)", aliases: ["screentime", "screen time"], def: "Self-reported hours of TV plus computer/device use per day, from two NHANES questions. Coded 0–5 hours as reported, 8 meaning eight or more." },
  { group: "variables", term: "Age", unit: "years", def: "Age at the survey, 12–17 in this cohort." },
  { group: "variables", term: "Sex", aliases: ["male", "female", "sex_as_main_effect"], def: "Male or female as recorded by NHANES. Enters the models as 'Male' = 1. Boys average 18.9 U/L ALT, girls 13.6." },
  { group: "variables", term: "Race / ethnicity", aliases: ["raceethnicity", "race ethnicity"], def: "NHANES' six-category self-reported race and Hispanic origin. Available for grouping but not a model covariate in the revised protocol." },
  { group: "variables", term: "Energy", unit: "kcal/day", def: "Total calories on the recall day. Shown in the descriptive profile for context." },
  { group: "variables", term: "Diet weight", unit: "survey weight", aliases: ["dietweight", "diet weight"], def: "NHANES' day-1 dietary weight (WTDRD1): how many U.S. adolescents each person stands for. Every weighted statistic uses it." },
  { group: "variables", term: "SEQN", def: "The NHANES participant ID. An identifier, not a measurement — ignore it in analysis." },
  { group: "variables", term: "Survey PSU / stratum", aliases: ["surveypsu", "surveystratum", "survey psu", "survey stratum"], def: "NHANES' sampling design codes: which neighbourhood cluster and stratum a person was drawn from. Used to count clusters; not analysed as variables." },
];

/** Normalise a label so loose spellings hit the same entry. */
function norm(label: string): string {
  return label
    .toLowerCase()
    .replace(/[_\-]+/g, " ")
    .replace(/[()·:]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

const INDEX = new Map<string, GlossaryEntry>();
for (const entry of GLOSSARY) {
  INDEX.set(norm(entry.term), entry);
  for (const alias of entry.aliases ?? []) INDEX.set(norm(alias), entry);
}

/** Find the entry for a printed label, or null if there is none. */
export function lookup(label: string): GlossaryEntry | null {
  const key = norm(label);
  if (!key) return null;
  const hit = INDEX.get(key);
  if (hit) return hit;
  // "Mean ALT (U/L)" -> "mean alt" -> try the first word as a last resort,
  // but only for stat-like heads, never for arbitrary prose.
  const first = key.split(" ")[0];
  return first && first !== key && first.length > 1 ? (INDEX.get(first) ?? null) : null;
}

/** Plain-language description of each analysis tier, for the Overview. */
export const TIER_HELP: Record<string, string> = {
  basic:
    "Centre and spread of one column: count, mean, median, mode, min, max, standard deviation, variance. Start here.",
  medium:
    "Adds the shape of the distribution (skewness, kurtosis, normality), a confidence interval for the mean, and — if you pick a group — a test of whether the groups differ, with an effect size.",
  advanced:
    "Relationships: how the column correlates with every other numeric column, and a regression predicting it from them.",
  expert:
    "Can the models be trusted? Multicollinearity (VIF), residual diagnostics, the share above the published clinical threshold, and trend tests.",
  categorical:
    "For label columns like Sex: counts and proportions of each category, and a cross-tab against the other labels.",
};
