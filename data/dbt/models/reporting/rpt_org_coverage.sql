-- People per city: city managers, support staff and fleet executives against driver partners.
select
    c.state,
    c.city,
    count(distinct s.id) filter (where s.role = 'OPS_MANAGER') as city_managers,
    count(distinct s.id) filter (where s.role in ('SUPPORT_AGENT', 'SUPPORT_LEAD')) as support_staff,
    count(distinct s.id) filter (where s.role = 'FLEET_EXECUTIVE') as fleet_executives,
    count(distinct d.driver_id) filter (where d.onboarding_status = 'APPROVED') as approved_drivers,
    round(
        count(distinct d.driver_id) filter (where d.onboarding_status = 'APPROVED')
        / nullif(count(distinct s.id) filter (where s.role = 'FLEET_EXECUTIVE'), 0),
        1
    ) as drivers_per_fleet_executive
from {{ ref('dim_city') }} c
left join {{ ref('stg_staff') }} s on s.city_id = c.city_id
left join {{ ref('dim_driver') }} d on d.city_id = c.city_id
group by all
