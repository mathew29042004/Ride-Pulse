-- depends_on: {{ source('lake', 'trips') }}
-- One row per trip, with the timestamps also in Indian Standard Time.
select
    *,
    {{ ist('requested_at') }} as requested_at_ist,
    cast({{ ist('requested_at') }} as date) as request_date,
    hour({{ ist('requested_at') }}) as request_hour,
    dayname({{ ist('requested_at') }}) as request_weekday,
    status = 'COMPLETED' as is_completed,
    status in ('CANCELLED', 'NO_DRIVER_FOUND') as is_cancelled,
    status = 'NO_DRIVER_FOUND' as is_no_driver,
    case when assigned_at is not null then date_diff('second', requested_at, assigned_at) end
        as seconds_to_assign,
    case when arrived_at is not null and assigned_at is not null
        then date_diff('second', assigned_at, arrived_at) / 60.0 end as pickup_minutes,
    case when completed_at is not null and started_at is not null
        then date_diff('second', started_at, completed_at) / 60.0 end as ride_minutes
from {{ latest_snapshot('trips') }}
