import pandas as pd
import os
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from dotenv import load_dotenv
from datetime import date, datetime
from math import hypot
from zoneinfo import ZoneInfo
from api_fetch import (
    fetch_roadwork_data,
    fetch_traffic_data,
    fetch_static_heilbronn,
    fetch_realtime_heilbronn,
    fetch_weather_data,
)

def get_xml_data(element, path):
    found = element.find(path)
    if found is not None:
        return found.text
    else:
        return None

def _parse_datetime(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Europe/Berlin"))
    return parsed

def _coordinates_from_geometry(geometry):
    coordinates = geometry.get("coordinates") or {}
    if geometry.get("type") == "Point":
        return [coordinates] if len(coordinates) >= 2 else []

    points = []
    if isinstance(coordinates, list):
        for value in coordinates:
            if (
                isinstance(value, list)
                and len(value) >= 2
                and all(isinstance(item, (int, float)) for item in value[:2])
            ):
                points.append(value)
            elif isinstance(value, list):
                points.extend(
                    _coordinates_from_geometry(
                        {"type": geometry.get("type"), "coordinates": value}
                    )
                )
    return points

def _distance_km(longitude_a, latitude_a, longitude_b, latitude_b):
    latitude_scale = 111.0
    longitude_scale = 111.0
    return hypot(
        (longitude_a - longitude_b) * longitude_scale,
        (latitude_a - latitude_b) * latitude_scale,
    )

def _spatial_event_context(events, route_points):
    spatial_events = []
    if not route_points:
        return spatial_events

    route_longitudes = [point[0] for point in route_points]
    route_latitudes = [point[1] for point in route_points]
    route_min_longitude = min(route_longitudes) - 0.01
    route_max_longitude = max(route_longitudes) + 0.01
    route_min_latitude = min(route_latitudes) - 0.005
    route_max_latitude = max(route_latitudes) + 0.005

    for event in events:
        if not event["coordinates"]:
            continue
        event_longitudes = [point[0] for point in event["coordinates"]]
        event_latitudes = [point[1] for point in event["coordinates"]]
        if (
            max(event_longitudes) < route_min_longitude
            or min(event_longitudes) > route_max_longitude
            or max(event_latitudes) < route_min_latitude
            or min(event_latitudes) > route_max_latitude
        ):
            continue
        distance = min(
            _distance_km(
                route_point[0], route_point[1], point[0], point[1]
            )
            for route_point in route_points
            for point in event["coordinates"]
        )
        if distance <= 0.5:
            spatial_events.append({**event, "distance_km": distance})
    return spatial_events

def _event_rows_from_sources(roadwork_data, traffic_data):
    roadwork_events = []
    for feature in (roadwork_data or {}).get("features", []):
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        roadwork_events.append({
            "start_datetime": _parse_datetime(properties.get("starttime")),
            "end_datetime": _parse_datetime(properties.get("endtime")),
            "type": properties.get("type"),
            "coordinates": _coordinates_from_geometry(geometry),
        })

    traffic_events = []
    traffic_root = traffic_data if hasattr(traffic_data, "findall") else None
    for event in (
        traffic_root.findall("TrafficAndTravelEvent")
        if traffic_root is not None
        else []
    ):
        coordinates = []
        for coordinate in event.findall(
            "Location/Tic3Location/Shape/Coordinate"
        ):
            longitude = get_xml_data(coordinate, "Longitude")
            latitude = get_xml_data(coordinate, "Latitude")
            if longitude and latitude:
                coordinates.append((float(longitude), float(latitude)))
        traffic_events.append({
            "start_datetime": _parse_datetime(
                get_xml_data(event, "Duration/StartTime")
            ),
            "end_datetime": _parse_datetime(
                get_xml_data(event, "Duration/EndTime")
            ),
            "start_unknown": not bool(
                get_xml_data(event, "Duration/StartTime")
            ),
            "event_type": get_xml_data(
                event,
                "Event/Tic3Event/TrafficAndTravelEventCode",
            ),
            "coordinates": coordinates,
        })
    return roadwork_events, traffic_events

def _context_for_occurrence(events, occurrence):
    return [
        event for event in events
        if (
            (
                event["start_datetime"] is None
                or event["start_datetime"] <= occurrence
            )
            and (
                event["end_datetime"] is None
                or occurrence <= event["end_datetime"]
            )
        )
    ]

def prepare_data():
    """Build joined Heilbronn rows for realtime and influence analysis."""
    static_data = fetch_static_heilbronn()
    realtime_rows = fetch_realtime_heilbronn(static_data=static_data)
    if not realtime_rows:
        return []

    service_dates = sorted({
        row["service_date"]
        for row in realtime_rows
        if row.get("service_date")
    })
    start_date = (
        datetime.strptime(service_dates[0], "%Y%m%d").date()
        if service_dates
        else date.today()
    )
    end_date = (
        datetime.strptime(service_dates[-1], "%Y%m%d").date()
        if service_dates
        else start_date
    )
    roadwork_data = fetch_roadwork_data(
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
    )
    traffic_data = fetch_traffic_data(
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
    )
    weather_data = fetch_weather_data(
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
    ) or {}
    hourly = weather_data.get("hourly", {})
    weather_by_time = {
        value: {
            "temperature_2m": hourly.get("temperature_2m", [])[index],
            "precipitation": hourly.get("precipitation", [])[index],
            "wind_speed_10m": hourly.get("wind_speed_10m", [])[index],
        }
        for index, value in enumerate(hourly.get("time", []))
    }
    roadwork_events, traffic_events = _event_rows_from_sources(
        roadwork_data,
        traffic_data,
    )
    static_trips = static_data["trips_by_id"]
    routes = static_data["routes_by_id"]
    route_points_by_trip = static_data["route_points_by_trip"]
    event_cache = {}
    local_timezone = ZoneInfo("Europe/Berlin")
    rows = []

    for index, realtime_row in enumerate(realtime_rows, start=1):
        trip_id = realtime_row["trip_id"]
        trip = static_trips.get(trip_id, {})
        route_points = route_points_by_trip.get(trip_id, [])
        cache_key = (
            ("shape", trip.get("shape_id"))
            if trip.get("shape_id")
            else ("trip", trip_id)
        )
        if cache_key not in event_cache:
            event_cache[cache_key] = (
                _spatial_event_context(roadwork_events, route_points),
                _spatial_event_context(traffic_events, route_points),
            )
        route_roadworks, route_traffic = event_cache[cache_key]

        occurrence = None
        for key in ("realtime_arrival_time", "realtime_departure_time"):
            if realtime_row.get(key):
                occurrence = _parse_datetime(realtime_row[key])
                break
        weather = (
            weather_by_time.get(
                occurrence.astimezone(local_timezone).strftime(
                    "%Y-%m-%dT%H:00"
                )
            )
            if occurrence
            else None
        )
        roadworks = (
            _context_for_occurrence(route_roadworks, occurrence)
            if occurrence
            else []
        )
        traffic = (
            _context_for_occurrence(route_traffic, occurrence)
            if occurrence
            else []
        )
        rows.append({
            **realtime_row,
            "route_short_name": routes.get(
                trip.get("route_id"),
                {},
            ).get("route_short_name", realtime_row.get("route_short_name")),
            "temperature_2m": weather.get("temperature_2m") if weather else None,
            "precipitation": weather.get("precipitation") if weather else None,
            "wind_speed_10m": weather.get("wind_speed_10m") if weather else None,
            "roadwork_count": len(roadworks),
            "traffic_event_count": len(traffic),
            "nearest_roadwork_distance_km": min(
                (event["distance_km"] for event in roadworks),
                default=None,
            ),
            "nearest_traffic_distance_km": min(
                (event["distance_km"] for event in traffic),
                default=None,
            ),
            "roadwork_types": "|".join(sorted({
                event.get("type")
                for event in roadworks
                if event.get("type")
            })),
            "traffic_event_types": "|".join(sorted({
                event.get("event_type")
                for event in traffic
                if event.get("event_type")
            })),
        })
        if index % 100 == 0:
            print(
                f"Realtime-Rows angereichert: {index}/{len(realtime_rows)}",
                flush=True,
            )
    return rows

def main():
    # Dataframe erstellen für DB
    rows = prepare_data()
    df = pd.DataFrame(rows)

    # Env variable laden für DB connection
    load_dotenv(dotenv_path=Path(__file__).resolve().with_name(".env"))
    if df.empty:
        print("Keine Rows zum Speichern vorhanden.", flush=True)
        return rows

    # Duplikate entfernen
    keys = ["service_date", "trip_id", "stop_sequence", "stop_id",]
    df = df.drop_duplicates(subset=keys, keep="last")
    
    # Verbindung zur Datenbank herstellen und Tabelle erstellen, falls sie nicht existiert
    engine = create_engine(os.environ["DATABASE_URL"])
    table_name = "traffic_data"
    constraint_name = "traffic_data_trip_stop_unique"

    with engine.begin() as connection:
        if not inspect(connection).has_table(table_name):
            df.head(0).to_sql(table_name, connection, if_exists="fail", index=False,)

        quoted_table = connection.dialect.identifier_preparer.quote(table_name)
        quoted_constraint = connection.dialect.identifier_preparer.quote(constraint_name)
        quoted_keys = ", ".join(connection.dialect.identifier_preparer.quote(key) for key in keys)
        
        # Prüfen, ob der Unique Constraint bereits existiert und falls nicht, hinzufügen
        connection.execute(text(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = '{constraint_name}'
                ) THEN
                    ALTER TABLE {quoted_table}
                    ADD CONSTRAINT {quoted_constraint}
                    UNIQUE ({quoted_keys});
                END IF;
            END $$;
        """))

        # Temporäre Tabelle für Upsert erstellen und Daten einfügen
        staging_table = "traffic_data_stage"
        df.to_sql(staging_table, connection, if_exists="replace", index=False,)
        quoted_stage = connection.dialect.identifier_preparer.quote(staging_table)
        columns = ", ".join(connection.dialect.identifier_preparer.quote(column) for column in df.columns)
        update_columns = [
            column for column in df.columns if column not in keys
        ]
        updates = ", ".join(
            f"{connection.dialect.identifier_preparer.quote(column)} = "
            f"EXCLUDED.{connection.dialect.identifier_preparer.quote(column)}"
            for column in update_columns
        )
        
        # Upsert durchführen: Wenn ein Konflikt auftritt, werden die vorhandenen Zeilen aktualisiert
        connection.execute(text(f"""
            INSERT INTO {quoted_table} ({columns})
            SELECT {columns}
            FROM {quoted_stage}
            ON CONFLICT ({quoted_keys})
            DO UPDATE SET {updates}
        """))
        connection.execute(text(f"DROP TABLE {quoted_stage}"))

    # Clean up: Verbindung schließen
    engine.dispose()
    print(f"{len(df)} Rows per Upsert gespeichert.", flush=True)
    return rows


if __name__ == "__main__":
    main()