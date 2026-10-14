select
    c.id as city_id,
    c.name as city,
    c.slug,
    c.state,
    c.fare_multiplier,
    c.radius_km,
    count(z.id) as zones,
    count(z.id) filter (where z.is_airport) as airports
from {{ ref('stg_cities') }} c
left join {{ ref('stg_zones') }} z on z.city_id = c.id
group by all
