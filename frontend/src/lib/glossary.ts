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
  { group: "statistics", term: "mean", aliases: ["weighted mean", "weighted_mean", "unweighted_mean", "mean_alt", "weighted_mean_alt"], def: "The ordinary average: add everything up and divide by n. One extreme value can pull it a long way." },
  { group: "statistics", term: "median", aliases: ["weighted_median", "weighted_median_alt", "50th percentile"], def: "The middle value once everything is sorted — half the people are below it, half above. Unlike the mean it ignores extreme values, which is why it is the better 'typical' for a skewed measure like ALT." },
  { group: "statistics", term: "mode", def: "The value that appears most often. Ties are all reported." },
  { group: "statistics", term: "min / max", aliases: ["min", "max"], def: "The smallest and largest values actually observed." },
  { group: "statistics", term: "standard deviation", aliases: ["std", "sd", "weighted_sd", "weighted sd"], def: "How spread out the values are: the typical distance from the mean, in the same units as the data. About two-thirds of values fall within one SD of the mean if the distribution is roughly bell-shaped." },
  { group: "statistics", term: "variance", def: "The standard deviation squared. Same idea (spread), harder to read because its units are squared." },
  { group: "statistics", term: "standard error", aliases: ["se", "std_error", "standard_error", "standard_error_alt", "standard_error_mean_alt", "sem"], def: "How uncertain an estimate is — how much the mean (or a coefficient) would wobble if the study were repeated. Smaller with bigger n. Not the same as standard deviation, which describes the people, not the estimate." },
  { group: "statistics", term: "confidence interval", aliases: ["95% ci", "ci", "ci_low", "ci_high", "ci lower", "ci upper", "interval"], def: "The range of values compatible with the data. If the 95% interval for a coefficient includes zero, the data cannot tell that effect apart from no effect." },
  { group: "statistics", term: "p-value", aliases: ["p", "p_value", "p value", "p_values", "p_value_means"], def: "The chance of seeing a result at least this extreme if there were truly no effect. Small (below 0.05) means the pattern is hard to explain by sampling noise alone. It is NOT the probability the finding is true, and it says nothing about how big the effect is." },
  { group: "statistics", term: "alpha", def: "The cutoff used to call a p-value 'significant'. This study uses 0.05, the convention." },
  { group: "statistics", term: "statistically significant", aliases: ["statistically_significant", "significant", "significance"], def: "p below 0.05: the data are unlikely under 'no effect'. It does not mean the effect is large or important — read the effect size beside it." },
  { group: "statistics", term: "effect size", aliases: ["effect_size", "magnitude", "measure"], def: "How big a difference or relationship is, separate from whether it is 'significant'. A tiny effect can be significant in a big sample; that is why every test here reports both." },
  { group: "statistics", term: "estimate", aliases: ["coefficient", "coefficients", "coefficients_mean"], def: "In a regression table, the change in the outcome for a one-unit rise in that predictor, with the other predictors held fixed. Here the outcome is ln(ALT), so 0.03 means roughly a 3% higher ALT per unit." },
  { group: "statistics", term: "standardized beta", aliases: ["β", "beta", "standardized_beta", "standardized_betas", "std beta", "ranked_by_standardized_beta"], def: "The coefficient rescaled so every predictor is in standard-deviation units. It answers 'which predictor matters most?' — a β of 0.42 (BMI) is about three times the pull of 0.13 (Trig/HDL)." },
  { group: "statistics", term: "R²", aliases: ["r_squared", "r squared", "r-squared", "adj_r_squared", "adjusted_r_squared", "adjusted r²", "delta_r_squared", "delta r squared", "delta_r_squared_with_bmi", "r_squared_vs_single_factors", "r squared vs single factors", "r_squared_log_alt", "r squared log alt"], def: "The share of the outcome's variation the model explains, from 0 to 1. R² = 0.30 means the predictors together account for 30% of why ALT differs between adolescents; the other 70% is things not in the model." },
  { group: "statistics", term: "Pearson r", aliases: ["r", "correlation", "correlations", "pearson"], def: "How closely two columns move together in a straight line, from −1 to +1. 0 is no linear relationship; the sign says whether one rises as the other rises (+) or falls (−)." },
  { group: "statistics", term: "regression", aliases: ["ols", "wls", "model", "predictors", "outcome"], def: "Fitting a line (or plane) through the data to estimate how each predictor relates to the outcome while holding the others constant. WLS is the same thing with survey weights so the fit describes U.S. adolescents." },
  { group: "statistics", term: "residual", aliases: ["residuals", "large_residuals", "mean_residual", "diagnostics", "mean residual", "large residuals"], def: "The gap between what the model predicted for a person and what was actually measured. Residuals that fan out or curve mean the model is missing something." },
  { group: "statistics", term: "skewness", def: "Whether the distribution has a long tail on one side. Positive = a tail of high values (ALT is strongly right-skewed: most adolescents low, a few very high). 0 is symmetric." },
  { group: "statistics", term: "kurtosis", aliases: ["kurtosis_excess"], def: "How heavy the tails are compared with a bell curve. High kurtosis means more extreme values than a normal distribution would give." },
  { group: "statistics", term: "normality", aliases: ["detectably_non_normal", "normal"], def: "Whether the values follow a bell curve. Many tests assume they roughly do, which is why ALT is analysed on the log scale — the raw values are far from normal." },
  { group: "statistics", term: "log transform", aliases: ["ln(alt)", "logalt", "log", "natural log", "transformation_applied", "transformation_justified", "raw_scale_model", "log_transform"], def: "Modelling the natural logarithm of ALT instead of ALT itself. It pulls the long right tail in so the regression assumptions hold. Coefficients then read as percentage changes: a coefficient of 0.03 ≈ 3% higher ALT." },
  { group: "statistics", term: "VIF", aliases: ["vif", "multicollinearity", "high_multicollinearity", "max_vif", "rule_triggered"], def: "Variance inflation factor: how much two predictors overlap. Above 5 they are so similar the model cannot tell their effects apart. The largest here is 1.28, so no problem." },
  { group: "statistics", term: "quartile", aliases: ["quartiles", "q2", "q4"], def: "One quarter of the sample, after sorting by sugar intake. Q1 is the lowest-sugar quarter, Q4 the highest." },
  { group: "statistics", term: "ANOVA", aliases: ["anova", "f_statistic"], def: "One test of whether several group means (here the four sugar quartiles) differ at all. F near 1 and a large p means they do not." },
  { group: "statistics", term: "chi-square", aliases: ["chi_square", "chi square", "contingency", "table", "counts_elevated", "counts_total", "elevated_alt_chi_square"], def: "A test of whether a proportion (here % with elevated ALT) differs between groups. Works on counts, not means." },
  { group: "statistics", term: "trend test", aliases: ["trend_test", "cochran-armitage", "cochran armitage", "trend"], def: "Asks whether something rises (or falls) in order across ordered groups — e.g. does ALT climb step by step from quartile 1 to 4? One coefficient answers that instead of many pairwise comparisons." },
  { group: "statistics", term: "dose-response", aliases: ["dose response"], def: "More of the exposure → more of the outcome, in order. Finding one is a strong hint an association is real; this study finds none for sugar." },
  { group: "statistics", term: "degrees of freedom", aliases: ["df", "degrees_of_freedom"], def: "Roughly how many independent pieces of information a test has to work with. Reported alongside the test statistic; you rarely need to interpret it." },
  { group: "statistics", term: "test statistic", aliases: ["statistic", "t", "z", "test"], def: "The number a test computes before converting it to a p-value (t, z, F or chi-square). Bigger in magnitude = further from 'no effect'." },
  { group: "statistics", term: "weighted", aliases: ["weight", "survey weight", "weighting", "wtdrd1"], def: "Each adolescent counts in proportion to how many U.S. adolescents they represent, so results describe the country rather than whoever NHANES happened to recruit." },
  { group: "statistics", term: "clusters", aliases: ["cluster", "psu", "primary sampling unit"], def: "NHANES samples whole neighbourhoods, not individuals. The cluster count (30) is how many of those groups the sample came from; the classical standard errors used here do not adjust for it, so borderline p-values are approximate." },
  { group: "statistics", term: "cross-sectional", def: "Everything was measured at one visit. It can show what goes together, never what causes what." },
  { group: "statistics", term: "mediation", aliases: ["decomposition", "indirect", "direct effect", "total effect", "proportion_mediated", "attenuation_percent", "total_c", "direct_c_prime", "indirect_a_times_b", "path_a_sugar_to_bmi", "path_b_bmi_to_logalt"], def: "Splitting sugar's link to ALT into the part that travels through BMI (indirect) and the part that does not (direct). Comparing Model B with and without BMI is how that split is estimated." },
  { group: "statistics", term: "layer", aliases: ["claim layer"], def: "How strong a claim a result supports: descriptive (what the data look like), inferential (what they suggest about the population), predictive (how well one thing predicts another). Never causal." },
  { group: "statistics", term: "IQR", aliases: ["iqr", "interquartile range"], def: "The middle 50% of values (75th percentile minus 25th). Used by the outlier rule: anything more than 1.5 × IQR beyond the box is flagged." },
  { group: "statistics", term: "at or above", aliases: ["at_or_above", "proportion_at_or_above", "below"], def: "The share of the sample at or past a published cutoff — for ALT, the pediatric thresholds of 22 U/L (girls) and 26 U/L (boys)." },
  { group: "statistics", term: "ECDF", aliases: ["cumulative share", "cumulative"], def: "The cumulative curve: for any value on the x-axis, the height is the share of people at or below it. Read percentiles straight off it." },
  { group: "statistics", term: "Q-Q plot", aliases: ["q-q", "qq"], def: "Data quantiles plotted against what a normal distribution would give. Points on the diagonal = normal; a curve away from it = skew." },
  { group: "statistics", term: "density", aliases: ["kde", "bandwidth"], def: "A smoothed histogram. Bandwidth is how much smoothing; wider hides bumps, narrower shows noise." },
  { group: "statistics", term: "bootstrap", def: "Resampling the data many times with replacement to see how much an estimate wobbles. A way to get uncertainty without assuming a bell curve." },

  { group: "statistics", term: "null hypothesis", aliases: ["null", "alternative hypothesis"], def: "The starting assumption a test tries to contradict: that there is no effect, no difference, no relationship. A p-value measures how badly the data fit it; a small p is evidence against the null, never proof of the alternative." },
  { group: "statistics", term: "false positive", aliases: ["type i error", "type 1 error"], def: "Calling an effect real when it is not. Testing at alpha = 0.05 accepts a 5% chance of this on every single test — which is why running many tests without a correction inflates it (see multiplicity)." },
  { group: "statistics", term: "false negative", aliases: ["type ii error", "type 2 error"], def: "Missing a real effect because the sample was too small or too noisy to detect it. It is why 'not significant' means 'not detected here', not 'shown to be zero'." },
  { group: "statistics", term: "statistical power", aliases: ["power", "underpowered"], def: "The chance a study would detect an effect of a given size if it exists. Small samples have low power, so a null result from 314 people rules out large effects far better than small ones." },
  { group: "statistics", term: "multiplicity", aliases: ["multiple testing", "multiple comparisons", "correction", "uncorrected"], def: "The more tests you run, the more 'significant' results appear by luck alone. This study handles it by pre-specifying ONE primary test and labelling everything else supporting or exploratory, rather than by correcting p-values after the fact." },
  { group: "statistics", term: "pre-specified", aliases: ["pre-registered", "pre-registration", "protocol", "protocol_step", "specification", "stratified_specification"], def: "Written down before the data were analysed. It is what separates a genuine test from a pattern found by looking — the protocol step number beside each result points to where in the written methods it was declared." },
  { group: "statistics", term: "percentile", aliases: ["quantile", "q1", "q3", "split_at", "cutpoints", "median split", "median_split", "median_split_chi_square", "dataset_median_split"], def: "The value below which a given share of the sample falls. Q1 (25th) and Q3 (75th) bound the middle half; a median split cuts the sample in two at the 50th to compare halves." },
  { group: "statistics", term: "z-score", aliases: ["z score", "z_score_gt_3", "standardized value"], def: "How many standard deviations a value sits from the mean. Beyond ±3 is unusual enough that the engine counts it as one candidate definition of an outlier." },
  { group: "statistics", term: "outlier", aliases: ["outliers", "iqr_fences", "iqr_rule", "iqr rule", "fences", "recommended_rule"], def: "A value far from the rest. The engine reports two rules — beyond 3 SDs, and beyond 1.5 × IQR past the quartiles — and recommends the IQR one for skewed columns, because a long tail drags the mean and SD with it. Nothing is ever deleted; being flagged is not being wrong." },
  { group: "statistics", term: "confidence level", aliases: ["confidence_level", "95%"], def: "How often intervals built this way would contain the true value across repeated samples — 95% here. Raising it widens the interval; it buys coverage with precision." },
  { group: "statistics", term: "eta squared", aliases: ["eta_squared", "η²"], def: "ANOVA's effect size: the share of total variation that lies between the groups rather than within them. 0.075 for sex means about 7.5% of the spread in ALT is explained by which group someone is in." },
  { group: "statistics", term: "Cramér's V", aliases: ["cramers_v", "cramer's v"], def: "The effect size for a chi-square test: how strongly two labels are associated, from 0 (unrelated) to 1 (perfectly predictable). Chi-square says whether; this says how much." },
  { group: "statistics", term: "Shapiro–Wilk", aliases: ["shapiro-wilk", "shapiro", "shapiro_p"], def: "A formal test of whether values follow a bell curve. In a sample of hundreds it rejects normality on tiny, harmless departures, so read it beside the skewness number and the Q-Q plot rather than alone." },
  { group: "statistics", term: "assumptions", aliases: ["assumes", "assumption_warning", "any_check_significant", "checks", "diagnostic"], def: "The conditions a test needs before its p-value means anything — roughly normal values, similar spreads, independent observations, a straight-line relationship. The expert tier checks them and says so when one fails, because a p-value from a violated assumption is just a number." },
  { group: "statistics", term: "heteroscedasticity", aliases: ["constant variance", "homoscedasticity", "fan shape"], def: "Residuals that spread wider at one end than the other, so the model is more wrong for some people than others. It is what the residuals-against-fitted plot looks for, and modelling log(ALT) instead of ALT is the fix used here." },
  { group: "statistics", term: "confounder", aliases: ["confounding", "confounders", "common cause"], def: "Something that affects both the exposure and the outcome and so creates a link between them that is not their own. BMI is the candidate confounder (or mediator) here — that is exactly why the primary model includes it." },
  { group: "statistics", term: "covariate", aliases: ["control", "controls", "adjusted", "adjustment", "held constant", "candidates", "how_to_run", "why_it_is_not_automatic"], def: "A variable put in the model not because it is the question but to hold it fixed while the question is asked. 'Adjusted for age and sex' means the reported effect is the part not explained by them." },
  { group: "statistics", term: "stratified", aliases: ["stratification", "stratified_models", "subgroup", "strata"], def: "Fitting the same model separately inside each group (here boys and girls) instead of pooling everyone. It shows whether a relationship looks different by group, but splitting the sample also shrinks it, so subgroup results are exploratory by default." },
  { group: "statistics", term: "intercept", aliases: ["const", "constant"], def: "The model's predicted outcome when every predictor is zero. Here that would be a newborn with a BMI of 0, so it is fitted but kept out of the coefficient tables — it is machinery, not a finding." },
  { group: "statistics", term: "joint test", aliases: ["joint_test", "f-test", "f test", "nested model test", "added_predictors"], def: "One test asking whether a SET of predictors adds anything, instead of testing each separately. Used here to ask whether the Trig/HDL ratio and HbA1c together improve the model over lifestyle alone (they do)." },
  { group: "statistics", term: "percent change", aliases: ["percent_change_in_alt", "percent_change_in_alt_per_quartile", "percent_change_per_point", "u_per_litre_per_point", "u_per_litre_significance"], def: "Because the outcome is log(ALT), a coefficient converts to a percentage: exp(b) − 1. A coefficient of 0.129 per risk point is about a 13.7% higher ALT per point, which is roughly 2.5 U/L at this sample's average." },
  { group: "statistics", term: "monotonic", aliases: ["gradient", "ordered", "direction"], def: "Moving steadily in one direction across ordered groups, without reversing. A monotonic rise across sugar quartiles is what a real dose-response would look like; these quartiles do not show one." },
  { group: "statistics", term: "association", aliases: ["associated", "relationship", "correlation vs causation"], def: "Two things moving together. Every result on this site is an association: it says what goes with what in the same people at the same moment, and cannot say which one moved the other, or whether a third thing moved both." },
  { group: "statistics", term: "sampling error", aliases: ["random error", "noise", "chance", "covers"], def: "The wobble that comes from measuring a sample rather than everybody. Confidence intervals and p-values quantify only this — not bad measurement, not selection, not a missing variable." },
  { group: "statistics", term: "generalizability", aliases: ["external validity", "population", "represents"], def: "Whether a finding extends beyond the people measured. NHANES weights buy generalizability to U.S. adolescents in 2017–2018; they say nothing about other countries or other years." },
  { group: "statistics", term: "complete-case analysis", aliases: ["listwise deletion", "missing", "missing data", "dropped"], def: "Analysing only the people with every variable present, which is what this study does. It is honest but costly — 107 adolescents were dropped for incomplete data — and it assumes the people dropped are not systematically different." },
  { group: "statistics", term: "imputation", def: "Filling missing values with estimates so a row can be kept. This engine never does it: a missing cell stays missing and the row is dropped, because inventing data is the one thing a statistics tool should not do quietly." },
  { group: "statistics", term: "Freedman–Diaconis rule", aliases: ["freedman-diaconis", "bin width", "bins", "bin"], def: "How the histogram picks its bar width: from the IQR and the sample size rather than a fixed number of bars. A fixed count under-bins a skewed column and hides the tail." },
  { group: "statistics", term: "information loss", aliases: ["information_loss", "dichotomized", "dichotomizing"], def: "What you give up by cutting a continuous measurement into groups — a median split throws away every distinction within each half, so 22.6 and 45 count the same. The engine flags it whenever it does this." },
  { group: "statistics", term: "sensitivity check", aliases: ["sensitivity", "robustness"], def: "Re-running an analysis a different reasonable way to see whether the answer holds — a second diet day, a different outlier rule. If the conclusion flips, it was resting on the choice rather than the data." },
  { group: "statistics", term: "layer: descriptive", aliases: ["descriptive"], def: "Summaries of the people actually measured — means, counts, spreads. True of this sample by construction; no inference involved." },
  { group: "statistics", term: "layer: inferential", aliases: ["inferential"], def: "Statements about the wider population, carrying uncertainty — tests, confidence intervals, weighted estimates." },
  { group: "statistics", term: "layer: predictive", aliases: ["predictive"], def: "How well one thing can be predicted from others — regression, R², the machine-learning model. Prediction is not explanation: a predictor can work well and still not be a cause." },
  { group: "statistics", term: "SHAP", aliases: ["shap", "contribution", "drivers", "mean_abs_shap", "contribution_log"], def: "A method that splits one prediction into a contribution per input, all adding up to the gap between the baseline and that prediction. It is how the Predict page can say which input pushed this particular estimate up or down." },
  { group: "statistics", term: "baseline", aliases: ["base_value", "baseline_alt", "expected value"], def: "What the model predicts before knowing anything about the individual — the average outcome. Every SHAP contribution is measured as a move away from it." },
  { group: "statistics", term: "gradient boosting", aliases: ["lightgbm", "gradient_boosting", "boosted trees", "booster"], def: "A prediction method that builds many small decision trees, each correcting the errors of the ones before. It captures curves and interactions a straight-line regression cannot — at the cost of being harder to read, which is what SHAP repairs." },
  { group: "statistics", term: "feature importance", aliases: ["importance", "gain", "gain_percent", "features", "feature"], def: "How much each input contributed across the whole model, not for one person. Ranks inputs; does not say which direction they push or whether they cause anything." },
  { group: "statistics", term: "cross-validation", aliases: ["folds", "5-fold", "rounds_per_fold", "validation", "held out", "scheme", "trained_on"], def: "Splitting the data into parts, training on some and scoring on the rest, then rotating. It estimates how the model does on people it has never seen. Here the folds are grouped by sampling unit so neighbours cannot leak between train and test." },
  { group: "statistics", term: "mean absolute error", aliases: ["mae", "mean_absolute_error_u_per_l"], def: "The average size of the model's miss, in the outcome's own units — 'typically wrong by about this many U/L'. Unlike R², it is read on the original scale." },
  { group: "statistics", term: "overfitting", aliases: ["overfit", "memorize"], def: "A model that learns the quirks of its training data and fails on new people. Cross-validation is how it is detected; stopping after a set number of boosting rounds is how it is limited here." },
  { group: "statistics", term: "hyperparameters", aliases: ["params", "learning_rate", "num_leaves", "min_data_in_leaf", "feature_fraction", "lambda_l2", "rounds", "objective", "metric", "bagging_freq", "force_row_wise", "num_threads", "verbosity"], def: "The model's settings, chosen before training rather than learned from data — how fast it learns, how complex each tree may get, how long it trains. All are printed on the Predict page so the model is reproducible." },
  { group: "statistics", term: "deterministic", aliases: ["seed", "reproducible", "same in same out"], def: "The same input always produces the same output, byte for byte. Fixed random seeds and caching make every number on this site reproducible — a demo that shifts between refreshes cannot be checked by anyone." },

  { group: "statistics", term: "group comparison", aliases: ["groups", "group_column", "n_groups", "group by", "by group"], def: "Computing the same statistic separately for each category and testing whether they differ. Picking a group column on the Overview turns a single summary into this comparison, with an effect size beside the test." },
  { group: "statistics", term: "proportion", aliases: ["proportions", "share", "percentage", "prevalence", "percent"], def: "The fraction of a sample in some category, usually shown as a percent. Proportions get their own tests (chi-square) because they are built from counts, not from averages." },
  { group: "statistics", term: "distribution", aliases: ["distributions", "spread of values"], def: "How the values of one column are spread out — where they cluster, how far they reach, whether they lean one way. Two columns can share a mean and have completely different distributions, which is why this site draws them." },
  { group: "statistics", term: "distinct values", aliases: ["unique", "levels", "categories"], def: "How many different values a column takes. A handful means it is really a label (Sex, race); hundreds means it is a measurement." },
  { group: "statistics", term: "unit", aliases: ["units", "display_unit", "display_factor", "u/l", "scale of measurement"], def: "What a number is measured in — U/L for ALT, grams per day for sugar, kg/m² for BMI. Coefficients only mean something once you know the unit they are 'per'." },
  // ---- study design -------------------------------------------------------
  { group: "study", term: "NHANES", aliases: ["nhanes 2017–2018", "nhanes 17–18"], def: "The National Health and Nutrition Examination Survey, run by the CDC. It interviews, examines and takes blood from a sample chosen to represent the whole U.S. population. This study uses the 2017–2018 cycle." },
  { group: "study", term: "Model A", aliases: ["lifestyle model", "lifestyle_model", "lifestyle_model_full_sample"], def: "The lifestyle-only regression: ln(ALT) on sugar, screen time, age and sex. Runs on all 695 adolescents." },
  { group: "study", term: "Model B", aliases: ["combined model", "combined_model", "combined_model_with_bmi", "full model", "total_model", "direct_model", "linear_model_b_with_bmi"], def: "Model A plus the two metabolic markers, the Trig/HDL ratio and HbA1c. Fitted twice — without BMI (sugar's total link to ALT) and with BMI (its direct link). It needs fasting blood, so n = 314." },
  { group: "study", term: "primary test", aliases: ["primary", "primary_test"], def: "The one test the study was designed to answer, chosen before looking at the data: is sugar's coefficient in Model B with BMI different from zero? It is not (p = 0.30)." },
  { group: "study", term: "supporting", def: "A pre-planned analysis that backs up or qualifies the primary test — dose-response, R² comparison, the descriptive profile." },
  { group: "study", term: "exploratory", def: "Looked at after the main question, without correction for multiple testing. Interesting, but it needs its own study to confirm — the sex split and the risk score." },
  { group: "study", term: "elevated ALT", aliases: ["altelevated", "alt elevated", "elevated_alt", "percent_elevated_alt", "percent elevated", "% elevated", "percent_elevated_alt_unweighted", "count_elevated"], def: "ALT above the pediatric screening cutoff: more than 26 U/L for boys, more than 22 U/L for girls (Schwimmer 2010, adopted by NASPGHAN 2017). About 10.5% of U.S. adolescents are above it." }, 
  { group: "study", term: "fasting subsample", aliases: ["fasting", "fasting_subsample_n"], def: "NHANES only measures triglycerides on the morning participants who fasted overnight. That is why anything using the Trig/HDL ratio has n = 314 instead of 695." },
  { group: "study", term: "attrition", aliases: ["cohort", "removed", "remaining"], def: "Who was dropped and why on the way from all 9,254 NHANES participants to the 695 adolescents analysed: age 12–17, a reliable diet recall, no hepatitis B or C, and complete data." },
  { group: "study", term: "risk score", aliases: ["riskscore", "risk_score", "score", "bands", "composite risk score"], def: "0–6 points: one for each of sugar, screen time, Trig/HDL, HbA1c and BMI above this cohort's median, plus one for being male. Mean ALT rises about 13.7% per point — but the cutoffs are this sample's own medians, so it ranks these adolescents against each other rather than being a clinical tool." },
  { group: "study", term: "classical standard errors", aliases: ["classical", "wls · classical", "estimator"], def: "The textbook standard errors from a weighted least-squares fit — what the written protocol specifies. They do not adjust for NHANES' clustered sampling, so p-values near 0.05 are approximate." },
  { group: "study", term: "interaction", aliases: ["interaction_model", "interaction_tests", "sugarxmale", "ratioxmale", "slopes_differ_by_sex"], def: "A term testing whether a predictor's slope differs between groups — e.g. does the Trig/HDL slope differ for boys and girls? (It does, p = 0.04; the sugar slope does not.)" },
  { group: "study", term: "tier", aliases: ["basic", "medium", "advanced", "expert", "categorical"], def: "How deep the engine goes on a column: basic (centre and spread) → medium (shape, interval, group tests) → advanced (correlation, regression) → expert (diagnostics, thresholds, trend). Categorical is for label columns." },

  { group: "study", term: "claim grade", aliases: ["grade", "hierarchy"], def: "The tag on every step saying how much weight it can carry: primary (the pre-specified test), supporting (planned backup analyses), exploratory (looked at afterwards). Printed so a weak result cannot be quietly promoted into the headline." },
  { group: "study", term: "secondary data analysis", aliases: ["secondary analysis"], def: "Analysing data somebody else collected — here the CDC's. It buys a large, nationally representative sample; it means the questions asked were not designed for this study." },
  { group: "study", term: "fatty liver disease", aliases: ["nafld", "masld", "liver stress", "steatosis"], def: "Fat accumulating in the liver, now the commonest chronic liver disease in children and often symptomless. Raised ALT is the cheap blood marker that flags it, which is why ALT is this study's outcome." },
  { group: "study", term: "24-hour dietary recall", aliases: ["recall", "dr1", "day 1", "day 2", "diet recall", "two-day"], def: "A trained interviewer walks the participant through everything eaten in the past day. Only recalls NHANES judged reliable are used. One day is a noisy picture of a habit — a real limitation, and why the second day exists as a sensitivity check." },
  { group: "study", term: "NASPGHAN threshold", aliases: ["naspghan", "schwimmer", "clinical threshold", "clinical_threshold", "elevated_alt_thresholds", "elevated_alt_source", "thresholds", "threshold"], def: "The pediatric ALT screening cutoffs — above 26 U/L for boys, 22 U/L for girls — from Schwimmer et al. 2010 and adopted in the 2017 NASPGHAN guideline. Far lower than adult lab 'normal' ranges, which is the point." },
  { group: "study", term: "sparse band", aliases: ["sparse_bands", "small cell"], def: "A group with too few people to say much about — risk scores of 0, 5 and 6 have 5, 15 and 6 adolescents. Their means bounce around, so the trend across all bands is the trustworthy reading, not any single one." },
  { group: "study", term: "sugar quartile", aliases: ["sugarquartile", "quartile_edges_g", "sugar_range_g", "weighted_mean_sugar_g"], def: "Which quarter of the cohort someone's sugar intake falls in, cut at 62, 92 and 141 g/day. The dose-response step compares mean ALT across these four groups." },
  { group: "study", term: "weighted versus unweighted", aliases: ["percent_weighted", "percent_unweighted", "unweighted", "weighting_note"], def: "The weighted figure estimates U.S. adolescents; the unweighted one describes exactly who NHANES recruited. Both are printed — where they differ, the difference is what the survey design is doing." },

  { group: "study", term: "survey design", aliases: ["design", "complex survey", "sampling design"], def: "NHANES does not sample people at random: it picks neighbourhoods, then households, then people, oversampling some groups on purpose. The weights, strata and clusters are the bookkeeping that makes estimates from that design describe the country." },
  // ---- variables ----------------------------------------------------------
  { group: "variables", term: "ALT", unit: "U/L", aliases: ["alanine aminotransferase"], def: "Alanine aminotransferase, a liver enzyme measured in blood. It leaks out when liver cells are stressed or damaged, so higher ALT is the standard early marker of fatty-liver disease. This is the study's outcome." },
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
  // Fall back to the first word -- "standard error alt" is a standard error --
  // but only for words long enough to be a real term. A one- or two-letter
  // first word sends "r squared vs single factors" to Pearson r, which is a
  // wrong definition rather than a missing one.
  const first = key.split(" ")[0];
  return first && first !== key && first.length > 2 ? (INDEX.get(first) ?? null) : null;
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
