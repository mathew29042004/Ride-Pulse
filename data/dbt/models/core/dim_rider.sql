select
    r.id as rider_id,
    cast(r.created_at as date) as joined_on,
    r.rating,
    r.completed_trips,
    r.default_payment_method,
    r.is_blocked,
    r.night_safety,
    r.eco_points,
    r.co2_saved_g,
    r.was_referred,
    r.language,
    r.is_simulated
from {{ ref('stg_riders') }} r
