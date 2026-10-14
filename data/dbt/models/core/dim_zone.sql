select z.id as zone_id, z.code, z.name as zone, z.is_airport, z.demand_weight, c.city_id, c.city, c.state
from {{ ref('stg_zones') }} z
join {{ ref('dim_city') }} c on c.city_id = z.city_id
