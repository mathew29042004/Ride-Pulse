-- Driver partners with their vehicle, city and fleet executive (no personal data).
select
    d.id as driver_id,
    d.city_id,
    c.city,
    c.state,
    d.onboarding_status,
    d.gender,
    d.rating,
    d.rating_count,
    d.acceptance_rate,
    d.completed_trips,
    d.cancelled_trips,
    d.safety_score,
    d.accepts_parcels,
    d.accepts_intercity,
    d.fleet_executive_id,
    v.ride_type_id,
    rt.code as vehicle_class,
    v.fuel_type,
    v.fuel_type = 'EV' as is_electric,
    v.year as vehicle_year,
    cast(d.created_at as date) as joined_on
from {{ ref('stg_drivers') }} d
left join {{ ref('dim_city') }} c on c.city_id = d.city_id
left join {{ ref('stg_vehicles') }} v on v.driver_id = d.id and v.is_active
left join {{ ref('stg_ride_types') }} rt on rt.id = v.ride_type_id
