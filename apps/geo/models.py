from django.db import models

from apps.core.models import LatitudeField, LongitudeField

from .distance import haversine_km


class City(models.Model):
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(unique=True)
    state = models.CharField(max_length=60)
    center_lat = LatitudeField()
    center_lng = LongitudeField()
    radius_km = models.FloatField(help_text="Service area radius around the centre")
    fare_multiplier = models.DecimalField(
        max_digits=4, decimal_places=2, default=1, help_text="Scales the default fare card"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "cities"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def contains(self, lat: float, lng: float) -> bool:
        return haversine_km(self.center_lat, self.center_lng, lat, lng) <= self.radius_km


class Zone(models.Model):
    """A neighbourhood used for surge pricing, demand heatmaps and quick pick-up presets."""

    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name="zones")
    code = models.SlugField(max_length=40)
    name = models.CharField(max_length=80)
    center_lat = LatitudeField()
    center_lng = LongitudeField()
    radius_km = models.FloatField(default=2.5)
    is_airport = models.BooleanField(default=False)
    demand_weight = models.FloatField(
        default=1.0, help_text="Relative trip demand, used by the simulator"
    )

    class Meta:
        ordering = ["city__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["city", "code"], name="zone_code_unique_per_city")
        ]

    def __str__(self) -> str:
        return f"{self.name}, {self.city.name}"

    def distance_km(self, lat: float, lng: float) -> float:
        return haversine_km(self.center_lat, self.center_lng, lat, lng)


class LandmarkCategory(models.TextChoices):
    TRANSIT = "TRANSIT", "Station"
    AIRPORT = "AIRPORT", "Airport"
    MALL = "MALL", "Shopping"
    TECH_PARK = "TECH_PARK", "Tech park"
    LANDMARK = "LANDMARK", "Landmark"
    HOSPITAL = "HOSPITAL", "Hospital"
    EDUCATION = "EDUCATION", "Campus"


class Landmark(models.Model):
    """Well-known places offered as suggestions in the "Where to?" search."""

    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name="landmarks")
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=10, choices=LandmarkCategory.choices)
    address = models.CharField(max_length=160, blank=True)
    lat = LatitudeField()
    lng = LongitudeField()

    class Meta:
        ordering = ["city__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["city", "name"], name="landmark_unique_name")
        ]

    def __str__(self) -> str:
        return self.name
