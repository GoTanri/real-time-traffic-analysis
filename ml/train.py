import pandas as pd


from sklearn.dummy import DummyRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error

# BSP DATEN
df = pd.DataFrame({
    "hour": [6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    "previous_delay": [0, 2, 5, 4, 1, 0, 3, 2, 1, 4],
    "rain_mm": [0, 0, 1, 2, 0, 0, 1, 0, 0, 2],
    "delay_min": [1, 3, 7, 6, 2, 1, 4, 3, 2, 6],
})

features = ["hour", "previous_delay", "rain_mm"]
target = "delay_min"

X = df[features]
y = df[target]

# Chronologische Aufteilung
split = int(len(df) * 0.8) # len(df) Anzahl der zeilen 

X_train, X_test = X.iloc[:split], X.iloc[split:]
y_train, y_test = y.iloc[:split], y.iloc[split:]

# 1. Baseline: Vorhersage des Trainingsmittelwerts
baseline = DummyRegressor(strategy="mean")
baseline.fit(X_train, y_train)

# 2. Lineare Regression
model = LinearRegression()
model.fit(X_train, y_train)

# Prognosen
baseline_predictions = baseline.predict(X_test)
predictions = model.predict(X_test)

fehler = pd.DataFrame({
    "echt": y_test.values,
    "vorhergesagt": predictions.round(1),
    "abw": (y_test.values - predictions).round(1),
})
   
# Bewertung
print(
    "Baseline MAE:",
    round(mean_absolute_error(y_test, baseline_predictions), 2)
)

print(
    "Linear Regression MAE:",
    round(mean_absolute_error(y_test, predictions), 2)
)

print("Vorhersagen:", predictions)

print(fehler)