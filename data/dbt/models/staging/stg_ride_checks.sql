-- depends_on: {{ source('lake', 'ride_checks') }}
select * from {{ latest_snapshot('ride_checks') }}
