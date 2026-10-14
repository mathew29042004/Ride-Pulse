-- depends_on: {{ source('lake', 'ratings') }}
select * from {{ latest_snapshot('ratings') }}
