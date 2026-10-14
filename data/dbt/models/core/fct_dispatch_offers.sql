-- Every offer sent to a driver: the dispatch funnel (accepted, declined, timed out, countered).
select
    o.id as offer_id,
    o.trip_id,
    o.driver_id,
    o.status,
    o.dispatch_mode,
    o.round,
    o.distance_km,
    o.eta_minutes,
    o.rank_score,
    o.counter_amount,
    case when o.responded_at is not null then date_diff('second', o.offered_at, o.responded_at) end
        as response_seconds,
    t.city_id,
    t.service,
    t.request_date
from {{ ref('stg_trip_offers') }} o
join {{ ref('stg_trips') }} t on t.id = o.trip_id
