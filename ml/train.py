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
    load_dotenv(dotens_path=BASE_DIR /".env")
    engine = create_engine(os.environ["DATABASE_URL"])
    df = pd.read_sql("SELECT * FROM traffic_data", engine)
    engine.dispose()
    print(f"{len(df)} Rows aus traffic_data geladen.")
    return df
