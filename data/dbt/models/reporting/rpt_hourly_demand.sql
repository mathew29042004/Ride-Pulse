-- When people ride: requests by weekday and hour (IST), with how often nobody was free.
select
    c.city,
    t.request_weekday as weekday,
    t.request_hour as hour,
    count(*) as requests,
    round(avg(t.surge_multiplier), 2) as avg_surge,
    round(count(*) filter (where t.is_no_driver) / count(*), 3) as no_driver_rate
from {{ ref('fct_trips') }} t
join {{ ref('dim_city') }} c using (city_id)
group by all
