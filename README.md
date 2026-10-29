# Real-time traffic analysis

# Data collection - Gökhan

Pipeline zur Analyse von Verspaetungen im Raum Heilbronn. Die Pipeline
erzeugt eine bereinigte Row pro konkreter Fahrt, Haltestelle und
Realtime-Beobachtung. Fahrplan, Echtzeitdaten, Wetter, Baustellen,
Verkehrsmeldungen und Service-Alerts werden dabei in derselben Row
zusammengefuehrt.

## 1. Voraussetzungen

- Python 3.13 oder kompatible Python-Version
- PostgreSQL-Datenbank, zum Beispiel Neon
- Internetzugriff auf die externen Datenquellen

### Virtuelle Umgebung unter Windows

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2. Datenquellen und Endpoints

### GTFS Static

Der statische Feed kommt von GTFS.de:

```text
https://download.gtfs.de/germany/nv_free/latest.zip
```

Verwendete GTFS-Dateien:

| Datei                | Bedeutung                             |
| -------------------- | ------------------------------------- |
| `stops.txt`          | Haltestellen und Koordinaten          |
| `stop_times.txt`     | geplante Ankunfts- und Abfahrtszeiten |
| `trips.txt`          | konkrete Fahrten                      |
| `routes.txt`         | Linien und Verkehrsmittel             |
| `shapes.txt`         | geografischer Verlauf einer Fahrt     |
| `calendar.txt`       | regulaere Betriebstage                |
| `calendar_dates.txt` | Ausnahmen und Feiertage               |

Die Pipeline laedt den deutschlandweiten Feed, filtert die Haltestellen
ueber die offizielle Heilbronn-Grenze und behaelt danach nur Trips, die
mindestens eine Heilbronner Haltestelle bedienen.

### GTFS-Realtime

```text
https://realtime.gtfs.de/realtime-free.pb
```

Der Feed ist ein Protobuf-Snapshot und enthaelt unter anderem:

- aktuelle oder prognostizierte Ankunfts- und Abfahrtszeiten
- Verspaetungen in Sekunden
- `TripUpdate`-Daten pro Fahrt und Halt
- `Alert`-Entities fuer passende Stoerungsinformationen

Der Feed ist kein historisches Archiv. Fuer historische Trainingsdaten muss
der Snapshot regelmaessig gespeichert werden.

### Heilbronn-Grenze

```text
https://opendata.heilbronn.de/sites/default/files/Heilbronn_Stadtkreisgrenzen_Gen_0.geojson
```

Die Koordinaten der GTFS-Haltestellen werden gegen dieses Polygon geprueft.

### Baustellen

```text
https://api.mobidata-bw.de/datasets/traffic/roadworks/roadworks_geojson.json
```

Die Antwort ist GeoJSON. Die Pipeline filtert nach Zeitraum und ordnet
Baustellen anschliessend einer konkreten Fahrt zu, wenn sie maximal etwa
500 Meter von der Fahrtstrecke entfernt liegen.

### Verkehrsmeldungen

```text
https://api.mobidata-bw.de/datasets/traffic/incidents-bw/TIC3-Meldungen.xml
```

Die TIC3-Antwort ist XML. Meldungen werden anhand ihrer Koordinaten und
ihres bekannten Zeitraums mit der Fahrtstrecke verbunden. Meldungen ohne
Startzeit werden nicht automatisch verworfen, ein fehlendes Ende oder ein
fehlender Beginn wird als unbekannt behandelt.

### Wetter

Historische Daten:

```text
https://archive-api.open-meteo.com/v1/archive
```

Forecast-Fallback fuer aktuelle oder zukuenftige Tage:

```text
https://api.open-meteo.com/v1/forecast
```

Verwendete Variablen:

- `temperature_2m`
- `precipitation`
- `wind_speed_10m`

### TRIAS

TRIAS unter `https://efa-bw.de/trias` ist eine Anfrage-Schnittstelle fuer
konkrete Fahrplanauskuenfte und Verbindungen. Sie wird derzeit nicht fuer
die Massendatenerzeugung verwendet. GTFS Static und GTFS-Realtime sind fuer
die aktuelle Row-basierte Verspaetungsanalyse geeigneter.

## 3. GTFS-Verkehrsmittel (`route_type`)

| Wert | Verkehrsmittel    |
| ---: | ----------------- |
|    0 | Strassenbahn/Tram |
|    1 | U-Bahn/Metro      |
|    2 | Bahn/Zug          |
|    3 | Bus               |
|    4 | Faehre            |
|    5 | Seilbahn          |
|    6 | Gondelbahn        |
|    7 | Standseilbahn     |
|   11 | Oberleitungsbus   |
|   12 | Monorail          |

## 4. Verarbeitung und Row-Modell

Die zentralen Funktionen sind:

1. `fetch_static_heilbronn()`
   - laedt den GTFS-Static-Feed
   - filtert Heilbronner Haltestellen
   - verbindet Stops, Stop-Times, Trips, Routes und Shapes
   - baut ein wiederverwendbares statisches Mapping
2. `fetch_realtime_heilbronn(static_data=...)`
   - laedt den aktuellen GTFS-Realtime-Snapshot
   - verbindet Realtime-Daten mit `trip_id`, `stop_id` und `service_date`
   - verwirft Updates ohne echte Realtime-Zeit oder ohne Verspaetungswert
   - uebernimmt passende Service-Alerts
3. `prepare_data()`
   - laedt Wetter, Baustellen und TIC3-Meldungen
   - ordnet Einfluesse raeumlich und zeitlich der konkreten Fahrt zu
   - gibt die finalen Rows zurueck

Die Grundidentitaet einer Row ist:

```text
service_date + trip_id + stop_id/stop_sequence
```

Eine Fahrt kann mehrere Rows haben, eine pro Realtime-Stop-Update. Die
Fahrtstrecke wird ueber `shape_id` bestimmt. Falls keine verwertbare Shape
vorhanden ist, wird die Haltestellenfolge als Fallback verwendet.

Baustellen und Verkehr werden nicht nur direkt an der Haltestelle gesucht.
Eine Meldung wird der Row zugeordnet, wenn sie nahe an der gesamten
Fahrtstrecke liegt und zum beobachteten Realtime-Zeitpunkt aktiv ist.

## 5. Wichtige Ausgabefelder

### Zielvariable

- `delay_seconds`
- `arrival_delay_seconds`
- `departure_delay_seconds`

`delay_seconds` verwendet bevorzugt die Ankunftsverspaetung und faellt,
wenn diese fehlt, auf die Abfahrtsverspaetung zurueck. Die Rohfelder bleiben
separat erhalten. Fehlende Werte werden nicht kuenstlich erraten.

### Einflussvariablen

- `temperature_2m`
- `precipitation`
- `wind_speed_10m`
- `roadwork_count`
- `nearest_roadwork_distance_km`
- `traffic_event_count`
- `nearest_traffic_distance_km`
- `has_service_alert`
- `alert_count`
- `has_technical_alert`
- `alert_causes`
- `alert_effects`
- `alert_ids`
- `alert_headers`

Ein `NULL` bei einer Distanz bedeutet, dass kein passendes Ereignis
gefunden wurde. Das ist nicht dasselbe wie eine Distanz von `0`.

Service-Alerts werden nur angehaengt, wenn `trip_id`, `route_id` oder
`stop_id` passt und der Alert zum Realtime-Zeitpunkt aktiv ist. Ein Alert
muss nicht technisch sein, auch Unfall, Umleitung, Baustelle, Ausfall oder
andere Stoerungen werden als Einflussfaktor beruecksichtigt.

## 6. Lokaler Test

Nur importieren startet die Pipeline noch nicht:

```python
import prepare_data
```

Die Pipeline wird explizit ausgefuehrt:

```python
rows = prepare_data.prepare_data()
print(len(rows))
print(rows[:1])
```

Als Skript:

```powershell
.\.venv\Scripts\python.exe prepare_data.py
```

Dabei ruft `main()` die Funktion `prepare_data()` auf und schreibt die
Rows in PostgreSQL.

## 7. PostgreSQL und Neon

Die Pipeline verwendet:

```text
pandas -> SQLAlchemy -> psycopg -> PostgreSQL/Neon
```

Die Datei `.env` muss lokal eine `DATABASE_URL` enthalten. Die `.env`-Datei
ist in `.gitignore` eingetragen und darf nicht committed werden.

Beispielstruktur ohne echte Zugangsdaten:

```text
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST/DATABASE?sslmode=require
```

Benoetigte Pakete:

- `pandas`
- `sqlalchemy`
- `psycopg[binary]`
- `python-dotenv`

Vor dem ersten Lauf kann die Verbindung getestet werden:

```powershell
@'
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(Path.cwd() / ".env")
engine = create_engine(os.environ["DATABASE_URL"])

with engine.connect() as connection:
    print(connection.execute(text("SELECT 1")).scalar())

engine.dispose()
'@ | .\.venv\Scripts\python.exe -
```

Der erwartete Wert ist:

```text
1
```

`prepare_data.py` schreibt die Daten in die Tabelle `traffic_data`.
Die Speicherung verwendet einen PostgreSQL-Upsert. Als fachlicher
Schluessel gilt:

```text
service_date + trip_id + stop_sequence + stop_id
```

Ist dieser Schluessel noch nicht vorhanden, wird eine Row eingefuegt. Wenn
er bereits vorhanden ist, wird die Row mit den aktuellen Realtime-, Wetter-,
Baustellen-, Verkehrs- und Alert-Werten aktualisiert. Der `feed_timestamp`
wird dabei ebenfalls aktualisiert; er ist bewusst kein Bestandteil des
fachlichen Schluessels, weil ein neuer Feed-Snapshot keine neue Fahrt
darstellt.

Beim ersten Upsert-Lauf werden bereits vorhandene Mehrfachzeilen pro
fachlichem Schluessel auf die neueste Row reduziert und eine PostgreSQL
Unique-Constraint angelegt. Dadurch koennen spaetere GitHub-Action-Laeufe
dieselbe Row nicht mehrfach einfuegen.

Beispiele fuer SQLTools oder den Neon SQL Editor:

```sql
SELECT COUNT(*) AS row_count
FROM traffic_data;
```

```sql
SELECT
    service_date,
    trip_id,
    stop_id,
    stop_sequence,
    delay_seconds,
    roadwork_count,
    traffic_event_count,
    alert_count,
    has_service_alert
FROM traffic_data
ORDER BY service_date DESC
LIMIT 20;
```

## 8. GitHub Actions

Ein Action-Lauf startet das Skript einmalig:

```text
python prepare_data.py
```

Dafuer muss `DATABASE_URL` als GitHub-Repository-Secret hinterlegt werden.
Sie darf nicht im Workflow-Text stehen.

Beispiel fuer den relevanten Workflow-Teil:

```yaml
name: Collect traffic data

on:
  schedule:
    - cron: "*/5 * * * *"
  workflow_dispatch:

jobs:
  collect:
    runs-on: ubuntu-latest
    env:
      DATABASE_URL: ${{ secrets.DATABASE_URL }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install -r requirements.txt
      - run: python prepare_data.py
```

GitHub Actions bietet fuer geplante Workflows keine verlässlich garantierte
Ausfuehrung alle zwei Minuten. Das kleinste sinnvolle Cron-Intervall ist
typischerweise fuenf Minuten, und die Ausfuehrung kann bei hoher Auslastung
verzoegert werden. Fuer echte Zwei-Minuten-Abstaende ist ein dauerhafter
Worker, eine VM oder ein anderer Scheduler geeigneter.

Da der Realtime-Feed ein Snapshot ist, sollte fuer historische Analysen der
Zeitpunkt jedes Laufs gespeichert werden. `feed_timestamp` und
`retrieved_at` sind dafuer vorgesehen. Bei regelmaessigen Laeufen darf der
Duplikat-Schluessel den Snapshot-Zeitpunkt nicht ignorieren, sonst werden
unterschiedliche Realtime-Beobachtungen derselben Fahrt zusammengelegt.

## 9. Regressionsmodell

### Einflussfaktoren:

- Temperatur, Regen, Wind
- Baustellen
- Verkehrsbehinderungen/Engpässe (bpsw. überlastete Straßen)
- GTFS-Realtime-Service-Alerts, z. B. technische Probleme, Unfälle,
  Baustellen, Umleitungen oder Ausfälle

**Kontextfrage:**

_War diese konkrete Fahrt zum beobachteten **Zeitpunkt** wahrscheinlich von einer nahegelegenen **Baustelle**, **Wetterbedingungen**, **Störungsmeldung** oder **Verkehrsmeldung** betroffen?_

### Zielvariable:

- Verspätung

### Regressionsmodell

`y = β₀ + β₁X₁ + β₂X₂ + β₃X₃ + β₄X + ε`

(ε ist der Fehlerterm, Teil der Regression die nicht
erklärt werden konnte, z.B.:

Tatsächliche Verspätung ist 6min und Modell ermittelt 4min: ε = y - ŷ = 6 - 4 = 2. Eine Abweichung von 2min somit.)

**Terme**:

- y: tatsächliche Verspätung
- β₀: Grundwert bzw. Achsenabschnitt
- β₁, β₂, β₃, β₄: geschätzte Zusammenhänge der Einflussfaktoren mit der Verspätung
- X₁, X₂, X₃, X₄: Wetter, Baustellen, Verkehrsbehinderungen und Service Alerts
- ε: nicht durch das Modell erklärte Abweichung

Die Pipeline behauptet nicht, dass ein einzelnes Ereignis sicher die
Verspaetung verursacht hat. Sie liefert reproduzierbare Kontextvariablen,
die anschliessend statistisch oder mit einem Machine-Learning-Modell
ausgewertet werden koennen.

## 10. Bekannte Grenzen

- Der GTFS-Realtime-Feed ist kein historisches Archiv.
- Der Static-Feed wird aktuell pro Pipeline-Lauf erneut geladen.
- Verkehrsmeldungen koennen fehlende Start- oder Endzeiten haben.
- Die Ereignisdistanz ist eine Naeherung anhand von Routenpunkten und einem
  Schwellenwert von etwa 500 Metern.
- Ein Realtime-Snapshot enthaelt nur die vom Anbieter aktuell veroeffentlichten
  Fahrten und Updates.
- TRIAS wird derzeit nicht fuer die Row-Erzeugung benoetigt.

# KI - Erik

# Visualisierung - Mohamad
