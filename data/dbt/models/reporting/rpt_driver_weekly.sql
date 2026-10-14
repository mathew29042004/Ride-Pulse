-- Each driver's week: trips, earnings, hours online and earnings per online hour.
with trips as (
    select
        driver_id,
        date_trunc('week', request_date) as week,
        count(*) filter (where is_completed) as trips,
        sum(driver_earning + tip_amount) filter (where is_completed) as earnings,
        avg(rider_rating_of_driver) as avg_rating,
        sum(actual_distance_km) filter (where is_completed) as km
    from {{ ref('fct_trips') }}
    where driver_id is not null
    group by all
),
hours as (
    select driver_id, date_trunc('week', session_date) as week, sum(online_hours) as online_hours
    from {{ ref('fct_driver_sessions') }}
    group by all
)
select
    t.week,
    t.driver_id,
    d.city,
    d.vehicle_class,
    d.is_electric,
    t.trips,
    t.earnings,
    round(t.km, 1) as km,
    round(h.online_hours, 1) as online_hours,
    round(t.earnings / nullif(h.online_hours, 0), 2) as earnings_per_hour,
    round(t.avg_rating, 2) as avg_rating
from trips t
left join hours h using (driver_id, week)
left join {{ ref('dim_driver') }} d using (driver_id)
