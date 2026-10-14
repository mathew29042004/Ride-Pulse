-- Daily KPIs per city: demand, completion, revenue split and service mix.
select
    t.request_date,
    c.city,
    c.state,
    count(*) as requests,
    count(*) filter (where t.is_completed) as completed,
    count(*) filter (where t.is_cancelled) as cancelled,
    count(*) filter (where t.is_no_driver) as no_driver,
    round(count(*) filter (where t.is_completed) / count(*), 3) as completion_rate,
    sum(t.fare_total) as gross_bookings,
    sum(t.driver_earning) as driver_earnings,
    sum(t.platform_commission) as commission,
    sum(t.gst_amount) as gst,
    sum(t.discount_amount) as discounts,
    sum(t.tip_amount) as tips,
    round(avg(t.fare_total) filter (where t.is_completed), 2) as avg_fare,
    round(avg(t.pickup_minutes), 1) as avg_pickup_minutes,
    count(*) filter (where t.service = 'PARCEL') as parcels,
    count(*) filter (where t.service = 'RENTAL') as rentals,
    count(*) filter (where t.service = 'INTERCITY') as intercity,
    count(*) filter (where t.was_surge) as surge_trips,
    round(sum(t.co2_saved_g) / 1000.0, 1) as co2_saved_kg
from {{ ref('fct_trips') }} t
join {{ ref('dim_city') }} c using (city_id)
group by all
