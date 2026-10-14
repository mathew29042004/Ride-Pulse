-- For completed trips: fare = driver share + commission + fees + GST − discount, where the
-- fees (booking, airport, Sure Ride) must come out between ₹0 and ₹300.
select trip_id, fare_total, driver_earning, platform_commission, gst_amount, discount_amount,
    fare_total - driver_earning - platform_commission - gst_amount + discount_amount as implied_fees
from {{ ref('fct_trips') }}
where is_completed
  and not (fare_total - driver_earning - platform_commission - gst_amount + discount_amount between 0 and 300)
