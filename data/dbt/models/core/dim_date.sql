-- One row per day covering all trips (Indian Standard Time).
with bounds as (
    select min(request_date) as first_day, max(request_date) as last_day from {{ ref('stg_trips') }}
)
select
    cast(d as date) as date_day,
    year(d) as year,
    month(d) as month,
    monthname(d) as month_name,
    weekofyear(d) as week,
    dayname(d) as weekday,
    isodow(d) >= 6 as is_weekend
from bounds, range(first_day, last_day + interval 1 day, interval 1 day) as t(d)
