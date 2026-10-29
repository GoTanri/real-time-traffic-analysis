import requests
import xml.etree.ElementTree as ET
import csv
import io
import os
import tempfile
import zipfile
from google.transit import gtfs_realtime_pb2
from datetime import datetime, time, timezone

# Realtime-Daten
def fetch_realtime_data():
    try: 
        url = "https://realtime.gtfs.de/realtime-free.pb"
        response = requests.get(url, timeout=30)
        response.raise_for_status()  # Raise an error for bad responses (4xx or 5xx)
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(response.content)
        return feed
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while fetching data: {e}")
        return None
    except Exception as e:
        print(f"An error occurred while parsing GTFS-RT data: {e}")
        return None

def _gtfs_enum_name(enum_type, value):
    try:
        return enum_type.Name(value)
    except ValueError:
        return str(value)

def _alert_text(translated_string):
    if not translated_string.translation:
        return None
    return translated_string.translation[0].text or None

def _build_realtime_alerts(feed):
    alerts = []
    for entity in feed.entity:
        if not entity.HasField("alert"):
            continue
        alert = entity.alert
        header_text = _alert_text(alert.header_text)
        description_text = _alert_text(alert.description_text)
        cause = _gtfs_enum_name(
            gtfs_realtime_pb2.Alert.Cause,
            alert.cause,
        ) if alert.HasField("cause") else None
        effect = _gtfs_enum_name(
            gtfs_realtime_pb2.Alert.Effect,
            alert.effect,
        ) if alert.HasField("effect") else None
        if (
            cause == "UNKNOWN_CAUSE"
            and effect == "UNKNOWN_EFFECT"
            and not header_text
            and description_text
            and "Echtzeitdaten aufbereitet" in description_text
        ):
            continue
        time_ranges = [
            (time_range.start, time_range.end)
            for time_range in alert.active_period
        ]
        alerts.append({
            "alert_id": entity.id,
            "cause": cause,
            "effect": effect,
            "header_text": header_text,
            "description_text": description_text,
            "url": _alert_text(alert.url),
            "time_ranges": time_ranges,
            "selectors": [
                {
                    "agency_id": selector.agency_id,
                    "route_id": selector.route_id,
                    "trip_id": (
                        selector.trip.trip_id
                        if selector.HasField("trip")
                        else ""
                    ),
                    "stop_id": selector.stop_id,
                }
                for selector in alert.informed_entity
            ],
        })
    return alerts

def _alert_matches_row(alert, trip_id, route_id, stop_id, timestamp):
    def selector_matches(selector):
        if selector["agency_id"]:
            return False
        if selector["trip_id"] and selector["trip_id"] != trip_id:
            return False
        if selector["route_id"] and selector["route_id"] != route_id:
            return False
        if selector["stop_id"] and selector["stop_id"] != stop_id:
            return False
        return any((
            selector["trip_id"],
            selector["route_id"],
            selector["stop_id"],
        ))

    entity_matches = any(
        selector_matches(selector)
        for selector in alert["selectors"]
    )
    if not entity_matches:
        return False
    if not alert["time_ranges"]:
        return True
    return any(
        (start == 0 or timestamp >= start)
        and (end == 0 or timestamp <= end)
        for start, end in alert["time_ranges"]
    )

def _alerts_for_row(alerts, trip_id, route_id, stop_id, timestamp):
    return [
        alert for alert in alerts
        if _alert_matches_row(
            alert,
            trip_id,
            route_id,
            stop_id,
            timestamp,
        )
    ]

def diagnose_realtime_date_range():
    """Inspect the date range represented by the current realtime snapshot."""
    feed = fetch_realtime_data()
    if feed is None:
        raise RuntimeError("Der GTFS-Realtime-Feed konnte nicht geladen werden.")

    feed_timestamp = (
        datetime.fromtimestamp(feed.header.timestamp, tz=timezone.utc)
        if feed.header.timestamp
        else None
    )
    service_dates = []
    stop_times = []
    trip_update_count = 0
    stop_update_count = 0

    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        trip_update_count += 1
        trip = entity.trip_update.trip
        if trip.start_date:
            service_dates.append(trip.start_date)

        for update in entity.trip_update.stop_time_update:
            stop_update_count += 1
            for event_name in ("arrival", "departure"):
                if not update.HasField(event_name):
                    continue
                event = getattr(update, event_name)
                if event.HasField("time"):
                    stop_times.append(
                        datetime.fromtimestamp(
                            event.time,
                            tz=timezone.utc,
                        )
                    )

    service_date_values = sorted(set(service_dates))
    result = {
        "feed_timestamp_utc": (
            feed_timestamp.isoformat() if feed_timestamp else None
        ),
        "feed_entity_count": len(feed.entity),
        "trip_update_count": trip_update_count,
        "stop_update_count": stop_update_count,
        "service_date_min": service_date_values[0]
        if service_date_values else None,
        "service_date_max": service_date_values[-1]
        if service_date_values else None,
        "service_date_count": len(service_date_values),
        "stop_event_time_min_utc": (
            min(stop_times).isoformat() if stop_times else None
        ),
        "stop_event_time_max_utc": (
            max(stop_times).isoformat() if stop_times else None
        ),
        "service_dates": service_date_values,
    }

    if feed_timestamp and service_date_values:
        feed_date = feed_timestamp.date()
        result["service_date_age_days_min"] = (
            feed_date - datetime.strptime(
                service_date_values[-1],
                "%Y%m%d",
            ).date()
        ).days
        result["service_date_age_days_max"] = (
            feed_date - datetime.strptime(
                service_date_values[0],
                "%Y%m%d",
            ).date()
        ).days
    else:
        result["service_date_age_days_min"] = None
        result["service_date_age_days_max"] = None

    return result

def _point_in_ring(longitude, latitude, ring):
    inside = False
    for index, (x2, y2) in enumerate(ring):
        x1, y1 = ring[index - 1]
        if (y1 > latitude) != (y2 > latitude):
            crossing_longitude = (
                (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
            )
            if longitude < crossing_longitude:
                inside = not inside
    return inside

def _point_in_geometry(longitude, latitude, geometry):
    if not geometry:
        return False
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if geometry_type == "Polygon":
        return (
            bool(coordinates)
            and _point_in_ring(longitude, latitude, coordinates[0])
            and not any(
                _point_in_ring(longitude, latitude, hole)
                for hole in coordinates[1:]
            )
        )
    if geometry_type == "MultiPolygon":
        return any(
            _point_in_geometry(
                longitude,
                latitude,
                {"type": "Polygon", "coordinates": polygon},
            )
            for polygon in coordinates
        )
    return False

def fetch_static_heilbronn(
    static_feed_url="https://download.gtfs.de/germany/nv_free/latest.zip",
):
    """Load Heilbronn-relevant static GTFS data, including route shapes."""
    boundary = fetch_heilbronn_boundary_data() or {}
    features = boundary.get("features") or []
    boundary_geometry = features[0].get("geometry") if features else None
    if not boundary_geometry:
        raise ValueError("Die Heilbronn-Grenze konnte nicht geladen werden.")

    temporary_path = None
    try:
        with requests.get(static_feed_url, stream=True, timeout=900) as response:
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as file:
                temporary_path = file.name
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        file.write(chunk)

        with zipfile.ZipFile(temporary_path) as archive:
            stops_by_id = {}
            with archive.open("stops.txt") as raw:
                reader = csv.DictReader(
                    io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
                )
                for row in reader:
                    try:
                        longitude = float(row["stop_lon"])
                        latitude = float(row["stop_lat"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if _point_in_geometry(
                        longitude,
                        latitude,
                        boundary_geometry,
                    ):
                        stops_by_id[row["stop_id"]] = {
                            "stop_id": row["stop_id"],
                            "stop_name": row.get("stop_name"),
                            "longitude": longitude,
                            "latitude": latitude,
                        }

            stop_times_by_trip_stop = {}
            stop_times_by_trip = {}
            trip_ids = set()
            with archive.open("stop_times.txt") as raw:
                reader = csv.DictReader(
                    io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
                )
                for row in reader:
                    if row.get("stop_id") not in stops_by_id:
                        continue
                    trip_id = row.get("trip_id")
                    if not trip_id:
                        continue
                    trip_ids.add(trip_id)
                    stop_times_by_trip_stop[(trip_id, row["stop_id"])] = row
                    stop_times_by_trip.setdefault(trip_id, []).append(row)

            trips_by_id = {}
            route_ids = set()
            shape_ids = set()
            with archive.open("trips.txt") as raw:
                reader = csv.DictReader(
                    io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
                )
                for row in reader:
                    if row.get("trip_id") not in trip_ids:
                        continue
                    trips_by_id[row["trip_id"]] = row
                    if row.get("route_id"):
                        route_ids.add(row["route_id"])
                    if row.get("shape_id"):
                        shape_ids.add(row["shape_id"])

            routes_by_id = {}
            with archive.open("routes.txt") as raw:
                reader = csv.DictReader(
                    io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
                )
                for row in reader:
                    if row.get("route_id") in route_ids:
                        routes_by_id[row["route_id"]] = row

            shapes_by_id = {}
            if "shapes.txt" in archive.namelist():
                with archive.open("shapes.txt") as raw:
                    reader = csv.DictReader(
                        io.TextIOWrapper(
                            raw,
                            encoding="utf-8-sig",
                            newline="",
                        )
                    )
                    for row in reader:
                        shape_id = row.get("shape_id")
                        if shape_id not in shape_ids:
                            continue
                        try:
                            point = (
                                int(row["shape_pt_sequence"]),
                                float(row["shape_pt_lon"]),
                                float(row["shape_pt_lat"]),
                            )
                        except (KeyError, TypeError, ValueError):
                            continue
                        shapes_by_id.setdefault(shape_id, []).append(point)

        for points in shapes_by_id.values():
            points.sort(key=lambda point: point[0])

        route_points_by_trip = {}
        for trip_id, trip in trips_by_id.items():
            shape_points = shapes_by_id.get(trip.get("shape_id"))
            if shape_points:
                route_points_by_trip[trip_id] = [
                    (point[1], point[2]) for point in shape_points
                ]
            else:
                fallback = sorted(
                    stop_times_by_trip.get(trip_id, []),
                    key=lambda row: int(row.get("stop_sequence") or 0),
                )
                route_points_by_trip[trip_id] = [
                    (
                        stops_by_id[row["stop_id"]]["longitude"],
                        stops_by_id[row["stop_id"]]["latitude"],
                    )
                    for row in fallback
                    if row["stop_id"] in stops_by_id
                ]

        return {
            "stops_by_id": stops_by_id,
            "trips_by_id": trips_by_id,
            "routes_by_id": routes_by_id,
            "stop_times_by_trip_stop": stop_times_by_trip_stop,
            "stop_times_by_trip": stop_times_by_trip,
            "shapes_by_id": shapes_by_id,
            "route_points_by_trip": route_points_by_trip,
            "static_feed_url": static_feed_url,
        }
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.remove(temporary_path)

def fetch_realtime_heilbronn(
    static_data=None,
    static_feed_url="https://download.gtfs.de/germany/nv_free/latest.zip",
):
    """Fetch current realtime stop updates joined to static Heilbronn data."""
    static_data = static_data or fetch_static_heilbronn(static_feed_url)
    realtime_feed = fetch_realtime_data()
    if realtime_feed is None:
        raise RuntimeError("Der GTFS-Realtime-Feed konnte nicht geladen werden.")

    stops_by_id = static_data["stops_by_id"]
    trips_by_id = static_data["trips_by_id"]
    routes_by_id = static_data["routes_by_id"]
    stop_times_by_trip_stop = static_data["stop_times_by_trip_stop"]
    alerts = _build_realtime_alerts(realtime_feed)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    feed_timestamp = (
        datetime.fromtimestamp(
            realtime_feed.header.timestamp,
            tz=timezone.utc,
        ).isoformat()
        if realtime_feed.header.timestamp
        else None
    )
    rows = []
    for entity in realtime_feed.entity:
        if not entity.HasField("trip_update"):
            continue
        trip_update = entity.trip_update
        trip = trip_update.trip
        static_trip = trips_by_id.get(trip.trip_id)
        if not static_trip:
            continue
        route = routes_by_id.get(static_trip.get("route_id"), {})
        for update in trip_update.stop_time_update:
            stop = stops_by_id.get(update.stop_id)
            if not stop:
                continue
            static_stop_time = stop_times_by_trip_stop.get(
                (trip.trip_id, update.stop_id),
                {},
            )
            arrival = update.arrival if update.HasField("arrival") else None
            departure = (
                update.departure if update.HasField("departure") else None
            )
            arrival_delay = (
                arrival.delay
                if arrival and arrival.HasField("delay")
                else None
            )
            departure_delay = (
                departure.delay
                if departure and departure.HasField("delay")
                else None
            )
            arrival_time = (
                datetime.fromtimestamp(
                    arrival.time,
                    tz=timezone.utc,
                ).isoformat()
                if arrival and arrival.HasField("time")
                else None
            )
            departure_time = (
                datetime.fromtimestamp(
                    departure.time,
                    tz=timezone.utc,
                ).isoformat()
                if departure and departure.HasField("time")
                else None
            )
            delay_seconds = (
                arrival_delay
                if arrival_delay is not None
                else departure_delay
            )
            if (
                arrival_time is None
                and departure_time is None
            ) or delay_seconds is None:
                continue
            observed_timestamp = (
                arrival.time
                if arrival and arrival.HasField("time")
                else departure.time
            )
            matching_alerts = _alerts_for_row(
                alerts,
                trip.trip_id,
                static_trip.get("route_id", ""),
                update.stop_id,
                observed_timestamp,
            )
            rows.append({
                "retrieved_at": retrieved_at,
                "feed_timestamp": feed_timestamp,
                "trip_id": trip.trip_id,
                "service_date": trip.start_date,
                "stop_id": update.stop_id,
                "stop_name": stop.get("stop_name"),
                "longitude": stop.get("longitude"),
                "latitude": stop.get("latitude"),
                "stop_sequence": update.stop_sequence,
                "route_id": static_trip.get("route_id"),
                "route_short_name": route.get("route_short_name"),
                "route_type": route.get("route_type"),
                "service_id": static_trip.get("service_id"),
                "direction_id": static_trip.get("direction_id"),
                "shape_id": static_trip.get("shape_id"),
                "scheduled_arrival_time": static_stop_time.get(
                    "arrival_time"
                ),
                "scheduled_departure_time": static_stop_time.get(
                    "departure_time"
                ),
                "realtime_arrival_time": arrival_time,
                "realtime_departure_time": departure_time,
                "arrival_delay_seconds": arrival_delay,
                "departure_delay_seconds": departure_delay,
                "delay_seconds": delay_seconds,
                "alert_count": len(matching_alerts),
                "has_service_alert": bool(matching_alerts),
                "has_technical_alert": any(
                    alert["cause"] == "TECHNICAL_PROBLEM"
                    for alert in matching_alerts
                ),
                "alert_ids": "|".join(
                    alert["alert_id"] for alert in matching_alerts
                ),
                "alert_causes": "|".join(sorted({
                    alert["cause"]
                    for alert in matching_alerts
                    if alert["cause"]
                })),
                "alert_effects": "|".join(sorted({
                    alert["effect"]
                    for alert in matching_alerts
                    if alert["effect"]
                })),
                "alert_headers": "|".join(
                    alert["header_text"]
                    for alert in matching_alerts
                    if alert["header_text"]
                ),
            })
    return rows

# Wetterdaten
def fetch_weather_data(
    start_date="2026-09-01",
    end_date="2026-10-26",
):
    params = {
        "latitude": 49.1427,
        "longitude": 9.2109,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": "temperature_2m,precipitation,wind_speed_10m",
        "timezone": "Europe/Berlin",
    }
    try:
        response = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params=params,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while fetching weather data: {e}")
        try:
            response = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params=params,
                timeout=60,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as forecast_error:
            print(
                "An error occurred while fetching weather forecast: "
                f"{forecast_error}"
            )
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
        url = (
            "https://api.mobidata-bw.de/datasets/traffic/roadworks/"
            "roadworks_geojson.json"
        )
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
        url = (
            "https://opendata.heilbronn.de/sites/default/files/"
            "Heilbronn_Stadtkreisgrenzen_Gen_0.geojson"
        )
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while fetching Heilbronn boundary data: {e}")
        return None

# Verkehrsdaten
def fetch_traffic_data(
    start_date="2026-09-01",
    end_date="2026-10-26",
):
    try:
        url = (
            "https://api.mobidata-bw.de/datasets/traffic/incidents-bw/"
            "TIC3-Meldungen.xml"
        )
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

            if not start_text and not end_text:
                continue

            try:
                event_start = (
                    _parse_roadwork_datetime(start_text)
                    if start_text
                    else None
                )
                event_end = (
                    _parse_roadwork_datetime(end_text)
                    if end_text
                    else None
                )
            except ValueError:
                continue

            overlaps_period = (
                (event_end is None or event_end >= period_start)
                and (event_start is None or event_start <= period_end)
            )
            if overlaps_period:
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