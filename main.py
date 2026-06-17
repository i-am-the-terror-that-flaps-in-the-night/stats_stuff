import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import scipy
from scipy import stats

df = pd.read_csv("data/data.csv")

print(df.info())
print(df.describe())

print(np.mean(df))