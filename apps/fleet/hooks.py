"""Everything the driver-business features do when a trip completes."""

from apps.drivers.models import Vehicle

from . import ev, owners, quests


def after_trip(trip) -> None:
    owners.on_trip_completed(trip)
    quests.on_trip_completed(trip)
    if trip.vehicle_id:
        vehicle = Vehicle.objects.select_related("ride_type", "driver__user").get(
            pk=trip.vehicle_id
        )
        km = float(trip.actual_distance_km or trip.estimated_distance_km or 0)
        # Pickup driving is roughly the ETA at city speed (about 0.4 km a minute).
        pickup = float(trip.pickup_eta_min or 0) * 0.4
        ev.drain(vehicle, km + pickup, now=trip.completed_at)
