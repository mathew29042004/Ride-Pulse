-- How offers end, and how fast drivers respond, by city.
select
    c.city,
    o.status,
    count(*) as offers,
    round(avg(o.response_seconds), 1) as avg_response_seconds,
    round(avg(o.eta_minutes), 1) as avg_pickup_eta_minutes,
    round(avg(o.distance_km), 2) as avg_distance_km
from {{ ref('fct_dispatch_offers') }} o
join {{ ref('dim_city') }} c using (city_id)
group by all
