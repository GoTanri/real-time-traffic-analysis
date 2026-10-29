SELECT
    service_date,
    trip_id,
    stop_sequence,
    stop_id,
    COUNT(*) AS row_count
FROM traffic_data
GROUP BY
    service_date,
    trip_id,
    stop_sequence,
    stop_id
HAVING COUNT(*) > 1;