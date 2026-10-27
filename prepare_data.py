import pandas
from api_fetch import (
    fetch_calendar_data,
    fetch_calendar_dates_data,
    fetch_heilbronn_boundary_data,
    fetch_roadwork_data,
    fetch_routes_data,
    fetch_stop_times_data,
    fetch_stops_data,
    fetch_traffic_data,
    fetch_trips_data,
    fetch_weather_data,
)

def point_in_ring(longitude, latitude, ring):
    inside = False

    for index, (x2, y2) in enumerate(ring):
        x1, y1 = ring[index - 1]
        crosses_latitude = (y1 > latitude) != (y2 > latitude)

        if crosses_latitude:
            crossing_longitude = (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
            if longitude < crossing_longitude:
                inside = not inside

    return inside

def point_in_geometry(longitude, latitude, geometry):
    if not geometry:
        return False

    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates", [])

    if geometry_type == "Polygon":
        return (
            point_in_ring(longitude, latitude, coordinates[0])
            and not any(
                point_in_ring(longitude, latitude, hole)
                for hole in coordinates[1:]
            )
        )

    if geometry_type == "MultiPolygon":
        return any(
            point_in_geometry(
                longitude,
                latitude,
                {"type": "Polygon", "coordinates": polygon},
            )
            for polygon in coordinates
        )

    return False

def prepare_data():
    rows = []

    stops = fetch_stops_data() or []
    boundary = fetch_heilbronn_boundary_data() or {}
    features = boundary.get("features", [])
    geometry = features[0].get("geometry") if features else None

    for stop in stops:
        location = stop.get("stop_loc") or {}
        coordinates = location.get("coordinates") or []

        if len(coordinates) < 2:
            continue

        longitude, latitude = coordinates[:2]
        if not point_in_geometry(longitude, latitude, geometry):
            continue

        rows.append({
            "stop_id": stop.get("stop_id"),
            "stop_name": stop.get("stop_name"),
            "longitude": longitude,
            "latitude": latitude,
        })
        
    trips = fetch_trips_data() or []
    for trip in trips:
        rows.append({
            "trip_id": trip.get("trip_id"),
            "route_id": trip.get("route_id"),
            "service_id": trip.get("service_id"),
            "direction_id": trip.get("direction_id"),
        })
        
    routes = fetch_routes_data() or []
    for route in routes:
        rows.append({
            "route_id": route.get("route_id"),
            "route_short_name": route.get("route_short_name"),
            "route_type": route.get("route_type"),
        })
        
    stop_times = fetch_stop_times_data() or []
    for stop_time in stop_times:
        rows.append({
            "trip_id": stop_time.get("trip_id"),
            "stop_id": stop_time.get("stop_id"),
            "arrival_time": stop_time.get("arrival_time"),
            "departure_time": stop_time.get("departure_time"),
            "stop_sequence": stop_time.get("stop_sequence"),
        })

    calendar = fetch_calendar_data() or []
    for service in calendar:
        rows.append({
            "service_id": service.get("service_id"),
            "monday": service.get("monday"),
            "tuesday": service.get("tuesday"),
            "wednesday": service.get("wednesday"),
            "thursday": service.get("thursday"),
            "friday": service.get("friday"),
            "saturday": service.get("saturday"),
            "sunday": service.get("sunday"),
            "start_date": service.get("start_date"),
            "end_date": service.get("end_date"),
        })
        
    calendar_dates = fetch_calendar_dates_data() or []
    for calendar_date in calendar_dates:
        rows.append({
            "service_id": calendar_date.get("service_id"),
            "date": calendar_date.get("date"),
            "exception_type": calendar_date.get("exception_type"),
        })
        
    influence_rows = []
        
    weather_data = fetch_weather_data() or {}
    hourly_data = weather_data.get("hourly", {})
    for i in range(len(hourly_data.get("time", []))):
        influence_rows.append({
            "time": hourly_data.get("time", [])[i],
            "temperature_2m": hourly_data.get("temperature_2m", [])[i],
            "precipitation": hourly_data.get("precipitation", [])[i],
            "wind_speed_10m": hourly_data.get("wind_speed_10m", [])[i],
        })
    
    roadwork_data = fetch_roadwork_data() or []
    for roadwork in roadwork_data:
        features = roadwork.get("features", [])
        for feature in features:
            properties = feature.get("properties", {})
            geometry = feature.get("geometry", {})
            coordinates = geometry.get("coordinates", [])
            longtitude, latitude = coordinates[0] if len(coordinates) > 0 else None
            rows.append({
                "id": properties.get("id"),
                "type": properties.get("type"),
                "subtype": properties.get("subtype"),
                "description": properties.get("description"),
                "street": properties.get("street"),
                "direction": properties.get("direction"),
                "longtitude": longtitude,
                "latitude": latitude,
                "starttime": properties.get("starttime"),
                "endtime": properties.get("endtime"),
            })

    return rows, influence_rows
