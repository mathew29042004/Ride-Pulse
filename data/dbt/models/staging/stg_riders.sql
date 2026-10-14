-- depends_on: {{ source('lake', 'riders') }}
select * from {{ latest_snapshot('riders') }}
