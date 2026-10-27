import requests
import xml.etree.ElementTree as ET
from datetime import datetime, time, timezone

# Haltestellen
def fetch_stops_data():
    try: 
        url = "https://api.mobidata-bw.de/gtfs/stops"
        response = requests.get(url)
        response.raise_for_status()  # Raise an error for bad responses (4xx or 5xx)
        return response.json()  # Return the JSON data from the response
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while fetching data: {e}")
        return None

# Geplante Ankunfts- und Abfahrtszeiten
def fetch_stop_times_data():
    try: 
        url = "https://api.mobidata-bw.de/gtfs/stop_times"
        response = requests.get(url)
        response.raise_for_status()  # Raise an error for bad responses (4xx or 5xx)
        return response.json()  # Return the JSON data from the response
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while fetching data: {e}")
        return None

# Fahrten
def fetch_trips_data():
    try: 
        url = "https://api.mobidata-bw.de/gtfs/trips"
        response = requests.get(url)
        response.raise_for_status()  # Raise an error for bad responses (4xx or 5xx)
        return response.json()  # Return the JSON data from the response
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while fetching data: {e}")
        return None
    
# Linien
def fetch_routes_data():
    try: 
        url = "https://api.mobidata-bw.de/gtfs/routes"
        response = requests.get(url)
        response.raise_for_status()  # Raise an error for bad responses (4xx or 5xx)
        return response.json()  # Return the JSON data from the response
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while fetching data: {e}")
        return None

# Betriebstage
def fetch_calendar_data():
    try: 
        url = "https://api.mobidata-bw.de/gtfs/calendar"
        response = requests.get(url)
        response.raise_for_status()  # Raise an error for bad responses (4xx or 5xx)
        return response.json()  # Return the JSON data from the response
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while fetching data: {e}")
        return None

# Ausnahmen und Feiertage
def fetch_calendar_dates_data():
    try: 
        url = "https://api.mobidata-bw.de/gtfs/calendar_dates"
        response = requests.get(url)
        response.raise_for_status()  # Raise an error for bad responses (4xx or 5xx)
        return response.json()  # Return the JSON data from the response
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while fetching data: {e}")
        return None

# Wetterdaten
def fetch_weather_data():
    try: 
        url = "https://archive-api.open-meteo.com/v1/archive?latitude=49.1427&longitude=9.2109&start_date=2026-09-01&end_date=2026-10-26&hourly=temperature_2m,precipitation,wind_speed_10m&timezone=Europe%2FBerlin"
        response = requests.get(url)
        response.raise_for_status()  # Raise an error for bad responses (4xx or 5xx)
        return response.json()  # Return the JSON data from the response
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while fetching data: {e}")
        return None
    
def _parse_roadwork_datetime(value, end_of_day=False):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    if end_of_day and parsed.time() == time.min:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)

    return parsed.astimezone(timezone.utc)

def fetch_roadwork_data(
    start_date="2026-09-01",
    end_date="2026-10-26",
):
    try:
        url = "https://api.mobidata-bw.de/datasets/traffic/roadworks/roadworks_geojson.json"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        roadwork_data = response.json()

        period_start = _parse_roadwork_datetime(start_date)
        period_end = _parse_roadwork_datetime(end_date, end_of_day=True)
        if period_start > period_end:
            raise ValueError("start_date must be before or equal to end_date")

        filtered_features = []
        for feature in roadwork_data.get("features", []):
            properties = feature.get("properties") or {}
            roadwork_start = properties.get("starttime")
            roadwork_end = properties.get("endtime")

            if not roadwork_start or not roadwork_end:
                continue

            try:
                roadwork_start = _parse_roadwork_datetime(roadwork_start)
                roadwork_end = _parse_roadwork_datetime(roadwork_end)
            except ValueError:
                continue

            if roadwork_start <= period_end and roadwork_end >= period_start:
                filtered_features.append(feature)

        return {
            **roadwork_data,
            "features": filtered_features,
        }
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while fetching data: {e}")
        return None

def fetch_heilbronn_boundary_data():
    try:
        url = "https://opendata.heilbronn.de/sites/default/files/Heilbronn_Stadtkreisgrenzen_Gen_0.geojson"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while fetching Heilbronn boundary data: {e}")
        return None

def fetch_traffic_data(
    start_date="2026-09-01",
    end_date="2026-10-26",
):
    try:
        url = "https://api.mobidata-bw.de/datasets/traffic/incidents-bw/TIC3-Meldungen.xml"
        response = requests.get(url, timeout=30)
        response.raise_for_status()  # Raise an error for bad responses (4xx or 5xx)
        traffic_data = ET.fromstring(response.content)

        period_start = _parse_roadwork_datetime(start_date)
        period_end = _parse_roadwork_datetime(end_date, end_of_day=True)
        if period_start > period_end:
            raise ValueError("start_date must be before or equal to end_date")
        filtered_events = []

        for event in traffic_data.findall("TrafficAndTravelEvent"):
            start_text = next(
                (
                    element.text
                    for element in event.iter()
                    if element.tag.split("}")[-1] == "StartTime" and element.text
                ),
                None,
            )
            end_text = next(
                (
                    element.text
                    for element in event.iter()
                    if element.tag.split("}")[-1] == "EndTime" and element.text
                ),
                None,
            )

            if not start_text or not end_text:
                continue

            try:
                event_start = _parse_roadwork_datetime(start_text)
                event_end = _parse_roadwork_datetime(end_text)
            except ValueError:
                continue

            if event_start <= period_end and event_end >= period_start:
                filtered_events.append(event)

        for child in list(traffic_data):
            if child.tag.split("}")[-1] == "TrafficAndTravelEvent":
                traffic_data.remove(child)

        traffic_data.extend(filtered_events)
        return traffic_data  # Gefiltertes XML-Element
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while fetching data: {e}")
        return None
    except ET.ParseError as e:
        print(f"An error occurred while parsing XML data: {e}")
        return None