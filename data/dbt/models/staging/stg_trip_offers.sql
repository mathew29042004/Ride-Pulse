-- depends_on: {{ source('lake', 'trip_offers') }}
select * from {{ latest_snapshot('trip_offers') }}
