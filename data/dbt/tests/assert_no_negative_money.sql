select trip_id from {{ ref('fct_trips') }}
where fare_total < 0 or platform_commission < 0 or gst_amount < 0 or tip_amount < 0
   or cancellation_fee < 0 or boost_amount < 0
