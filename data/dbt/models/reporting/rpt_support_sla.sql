-- Support tickets: volume, how many met their SLA, and refunds, by category and priority.
select
    category,
    priority,
    count(*) as tickets,
    count(*) filter (where status in ('RESOLVED', 'CLOSED')) as resolved,
    count(*) filter (where resolved_at is not null and resolved_at <= sla_due_at) as within_sla,
    count(*) filter (where escalated) as escalated,
    round(
        avg(date_diff('minute', created_at, resolved_at)) filter (where resolved_at is not null) / 60.0, 1
    ) as avg_hours_to_resolve,
    sum(refund_amount) as refunds
from {{ ref('stg_support_tickets') }}
group by all
