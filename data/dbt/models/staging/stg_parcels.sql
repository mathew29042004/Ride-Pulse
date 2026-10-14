-- depends_on: {{ source('lake', 'parcels') }}
select * from {{ latest_snapshot('parcels') }}
