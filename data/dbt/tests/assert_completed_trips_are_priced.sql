-- A completed trip always has a driver, a fare and a distance.
select trip_id from {{ ref('fct_trips') }}
where is_completed and (driver_id is null or fare_total <= 0 or actual_distance_km is null)
