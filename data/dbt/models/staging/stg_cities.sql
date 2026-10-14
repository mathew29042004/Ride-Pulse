-- depends_on: {{ source('lake', 'cities') }}
select * from {{ latest_snapshot('cities') }}
