import os
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

from sklearn.compose import ColumnTransformer

# Einstellungen
BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
MODEL_PATH = RESULTS_DIR / "verspaetung_modell.joblib"
METRICS_PATH = RESULTS_DIR / "modell_metriken.csv"
PLOT_PATH = RESULTS_DIR / "vorhersage_vs_ist.png"

RANDOM_STATE = 42
TEST_ANTEIL = 0.2                  # ca 20 Prozent der Tage bzw fahrten als Test
MAX_ABS_VERSPAETUNG_MIN = 60       # Extremwerte darüber werden entfernt 
KEIN_EVENT_DISTANZ_KM = 10.0       # Ersatzwert, wenn kein Ereignis in der Nähe

NUM_FEATURES = [
    "stunde",
    "wochentag",
    "ist_wochenende",
    "stop_sequence",
    "direction_id",
    "temperature_2m",
    "precipitation",
    "wind_speed_10m",
    "roadwork_count",
    "has_roadwork",
    "nearest_roadwork_distance_km",
    "traffic_event_count",
    "has_traffic_event",
    "nearest_traffic_distance_km",
    "alert_count",
    "has_service_alert",
    "has_technical_alert",
]
CAT_FEATURES = ["route_short_name", "route_type"]

# Daten laden
def load_data() -> pd.DataFrame:
    load_dotenv(dotenv_path=BASE_DIR /".env")
    engine = create_engine(os.environ["DATABASE_URL"])
    df = pd.read_sql("SELECT * FROM traffic_data", engine) # Lies die Daten aus der Datenbank und speichert diese in einen DataFrame
    engine.dispose()
    print(f"{len(df)} Rows aus traffic_data geladen.")
    return df

# Test für die ersten 5 einträgen 
df_data = load_data()
display(df_data.head(5))


# Features bauen
def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Zielvariable in Minuten
    df["verspaetung_min"] = pd.to_numeric(df["delay_seconds"], errors="coerce") / 60.0

    # Beobachtungszeitpunkt (UTC -> Europe/Berlin)
    arrival = pd.to_datetime(df["realtime_arrival_time"], utc=True, errors="coerce")
    departure = pd.to_datetime(df["realtime_departure_time"], utc=True, errors="coerce")
    zeit = arrival.fillna(departure).dt.tz_convert("Europe/Berlin")
    df["stunde"] = zeit.dt.hour
    df["wochentag"] = zeit.dt.day_of_week
    df["ist_wochenende"] = (df["wochentag"] >= 5).astype(float)

    # Bool-Spalten -> 0/1
    for col in ["has_service_alert", "has_technical_alert"]:
        df[col] = df[col].astype(float)

    # Ereignis-Flags + Distanz: NULL = Kein Ereignis (nicht 0!)
    df["has_roadwork"] = (df["roadwork_count"].fillna(0) > 0).astype(float)
    df["has_traffic_event"] = (df["traffic_event_count"].fillna(0) > 0).astype(float)
    df["nearest_roadwork_distance_km"] = (df["nearest_roadwork_distance_km"].fillna(
        KEIN_EVENT_DISTANZ_KM 
    ))

    # Kategorische Spalten als Text
    df["route_short_name"] = df["route_short_name"].astype(str)
    df["route_type"] = df["route_type"].astype(str)

    # Numerische Saplten sicher in Zahlen umwandel
    for col in NUM_FEATURES:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Zeilen ohne Ziel oder mit Extremwerten entfernen
    df = df.dropna(subset=["verspaetung_min"])
    df = df[df["verspaetung_min"].abs() <= MAX_ABS_VERSPAETUNG_MIN]
    print(f"{len(df)} Rows nach Bereinigung (Ziel vorhanden, |Verspaetung| <= "
          f"{MAX_ABS_VERSPAETUNG_MIN} min).")
    return df

# Test für die ersten 5 rows
df_features = build_features(df_data)

print(df_features.head(5))