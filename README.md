# real-time-traffic-analysis

## Data collection & Formel - Gökhan

### Data input

**ÖPNV-Fahrplandaten – MobiData BW**

Basis: https://api.mobidata-bw.de/gtfs

Endpoint Verwendung

/stops Haltestellen

/stop_times Geplante Ankunfts- und Abfahrtszeiten

/trips Fahrten

/routes Linien

/calendar Betriebstage

/calendar_dates Ausnahmen und Feiertage

/feed_info Gültigkeit der Fahrplandaten

**Wetter – Open-Meteo**

Historische Wetterdaten, ohne API-Key für die normale Nutzung.

[Historische Wetter-API für Heilbronn – Beispiel Januar 2026](https://archive-api.open-meteo.com/v1/archive?latitude=49.1427&longitude=9.2109&start_date=2026-01-01&end_date=2026-01-31&hourly=temperature_2m,precipitation,wind_speed_10m&timezone=Europe%2FBerlin)

Verwendete Variablen:

- temperature_2m – Temperatur
- precipitation – Niederschlag
- wind_speed_10m – Windgeschwindigkeit
  Passe den Zeitraum an deine Fahrplandaten an.

**Baustellen und Verkehrsmeldungen – MobiData BW**

Datensatz Direkte URL

Baustellen (GeoJSON) roadworks_geojson.json

Verkehrsmeldungen (TIC3) TIC3-Meldungen.xml

Verkehrsmeldungen (DATEX II) incidents_lmsbw.datex2.xml

### Einflussfaktoren:

- Temperatur, Regen, Wind
- Baustellen
- Verkehrsbehinderungen/Engpässe (bpsw. überlastete Straßen)

### Zielvariable:

- Verspätung

### Regressionsmodell

`y = β₀ + β₁X₁ + β₂X₂ + β₃X₃ + ε`

(ε ist der Fehlerterm, Teil der Regression die nicht
erklärt werden konnte, z.B.:

Tatsächliche Verspätung ist 6min und Modell ermittelt 4min: ε = y - ŷ = 6 - 4 = 2. Eine Abweichung von 2min somit.)

**Terme**:

- y: tatsächliche Verspätung
- β₀: Grundwert bzw. Achsenabschnitt
- β₁, β₂, β₃: geschätzte Zusammenhänge der Einflussfaktoren mit der Verspätung
- X₁, X₂, X₃: Wetter, Baustellen und Verkehrsbehinderungen
- ε: nicht durch das Modell erklärte Abweichung

### Data output

(hier dann bestimmen ob csv und in welchem Format es gespeichert wird für das modell, ebenso alles was drin ist und in welcher datenbank bzw access auf die db)
(postgresql db wird in neon.tech gespeichert damit alle darauf zugreifen können)
