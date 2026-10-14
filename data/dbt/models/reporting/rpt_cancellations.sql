-- Who cancels, when, and how often nobody accepted: by city and ride type.
select
    c.city,
    rt.ride_type,
    count(*) as requests,
    count(*) filter (where t.cancelled_by = 'RIDER') as rider_cancelled,
    count(*) filter (where t.cancelled_by = 'DRIVER') as driver_cancelled,
    count(*) filter (where t.is_no_driver) as no_driver,
    sum(t.cancellation_fee) as cancellation_fees,
    round(count(*) filter (where t.is_cancelled) / count(*), 3) as cancel_rate
from {{ ref('fct_trips') }} t
join {{ ref('dim_city') }} c using (city_id)
join {{ ref('dim_ride_type') }} rt using (ride_type_id)
group by all
