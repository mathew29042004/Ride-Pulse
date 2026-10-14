-- depends_on: {{ source('lake', 'zones') }}
select * from {{ latest_snapshot('zones') }}
