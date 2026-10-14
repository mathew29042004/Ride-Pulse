-- depends_on: {{ source('lake', 'ride_types') }}
select * from {{ latest_snapshot('ride_types') }}
