select
    r.id as ride_type_id,
    r.code,
    r.name as ride_type,
    r.service,
    r.seats,
    coalesce(v.code, r.code) as vehicle_class,
    r.service_start_hour is not null as has_service_hours
from {{ ref('stg_ride_types') }} r
left join {{ ref('stg_ride_types') }} v on v.id = r.vehicle_type_id
