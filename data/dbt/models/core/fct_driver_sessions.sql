-- Time drivers spent online, per session (open sessions count up to now).
select
    s.id as session_id,
    s.driver_id,
    d.city_id,
    cast({{ ist('s.started_at') }} as date) as session_date,
    s.started_at,
    s.ended_at,
    date_diff('second', s.started_at, coalesce(s.ended_at, now())) / 3600.0 as online_hours
from {{ ref('stg_driver_sessions') }} s
left join {{ ref('stg_drivers') }} d on d.id = s.driver_id
