-- requested ≤ assigned ≤ arrived ≤ started ≤ completed, whenever the step happened.
select id from {{ ref('stg_trips') }}
where assigned_at < requested_at
   or arrived_at < assigned_at
   or started_at < arrived_at
   or completed_at < started_at
