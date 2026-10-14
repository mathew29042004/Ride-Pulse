-- depends_on: {{ source('lake', 'trip_events') }}
select * from {{ all_batches('trip_events') }}
