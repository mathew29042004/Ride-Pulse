-- depends_on: {{ source('lake', 'driver_sessions') }}
select * from {{ latest_snapshot('driver_sessions') }}
