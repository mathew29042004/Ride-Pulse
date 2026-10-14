-- depends_on: {{ source('lake', 'vehicles') }}
select * from {{ latest_snapshot('vehicles') }}
