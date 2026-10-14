-- depends_on: {{ source('lake', 'support_tickets') }}
select * from {{ latest_snapshot('support_tickets') }}
