-- depends_on: {{ source('lake', 'drivers') }}
select * from {{ latest_snapshot('drivers') }}
