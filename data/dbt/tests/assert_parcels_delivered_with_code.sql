-- Every completed parcel trip was handed over (delivery code verified).
select t.trip_id from {{ ref('fct_trips') }} t
left join {{ ref('stg_parcels') }} p on p.trip_id = t.trip_id
where t.service = 'PARCEL' and t.is_completed and p.delivered_at is null
