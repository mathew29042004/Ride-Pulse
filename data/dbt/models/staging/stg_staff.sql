-- depends_on: {{ source('lake', 'staff') }}
select * from {{ latest_snapshot('staff') }}
