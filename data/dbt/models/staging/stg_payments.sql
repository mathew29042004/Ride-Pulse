-- depends_on: {{ source('lake', 'payments') }}
select * from {{ latest_snapshot('payments') }}
