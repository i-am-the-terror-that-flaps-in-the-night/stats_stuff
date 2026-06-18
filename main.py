import matplotlib.pyplot as plt
import pandas as pd
from scipy.stats import skew, ttest_1samp, sem, t, f_oneway, chi2_contingency
import numpy as np

df = pd.read_csv("data/data.csv")

print(df.describe())
print("\n\n\n\n")

plt.hist(df["Score"], bins=10)
plt.title("Distribution of Scores")
plt.savefig("figures/score_distribution.pdf")
plt.close()

s = skew(df["Income"])

print("Skewness:", s)

df["Income_log"] = np.log(df["Income"])

plt.hist(df["Income"])
plt.savefig("figures/income_before.pdf")
plt.close()

plt.hist(df["Income_log"])
plt.savefig("figures/income_after.pdf")
plt.close()

t_stat, p = ttest_1samp(df["Score"], 75)

print("p =", p)

if p < 0.05:
    print("Significant")
else:
    print("Not Significant")

scores = df["Score"]

mean = np.mean(scores)
SE = sem(scores)

CI = t.interval(
    0.95,
    len(scores)-1,
    loc=mean,
    scale=SE
)

print(CI)

g8 = df[df["Grade"] == 8]["Score"]
g9 = df[df["Grade"] == 9]["Score"]
g10 = df[df["Grade"] == 10]["Score"]

F, p = f_oneway(g8, g9, g10)

print(F)
print(p)

table = pd.crosstab(
    df["Gender"],
    df["PassFail"]
)

print(table)

chi2, p, dof, expected = chi2_contingency(table)

print("chi2 =", chi2)
print("p =", p)

q1 = df["Score"].quantile(0.25)
q2 = df["Score"].quantile(0.50)
q3 = df["Score"].quantile(0.75)

print(q1, q2, q3)

q1 = df["Score"].quantile(0.25)
q3 = df["Score"].quantile(0.75)

iqr = q3 - q1

print(iqr)

lower = q1 - 1.5 * iqr
upper = q3 + 1.5 * iqr

outliers = df[
    (df["Score"] < lower) |
    (df["Score"] > upper)
]

print(outliers)