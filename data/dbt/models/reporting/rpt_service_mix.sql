-- Rides vs parcels vs rentals vs intercity, and the ride types inside each, per state.
select
    c.state,
    t.service,
    rt.ride_type,
    count(*) as requests,
    count(*) filter (where t.is_completed) as completed,
    sum(t.fare_total) as gross_bookings,
    round(avg(t.fare_total) filter (where t.is_completed), 2) as avg_fare,
    round(avg(t.actual_distance_km) filter (where t.is_completed), 2) as avg_km
from {{ ref('fct_trips') }} t
join {{ ref('dim_city') }} c using (city_id)
join {{ ref('dim_ride_type') }} rt using (ride_type_id)
group by all
