"""Monthly budgets per city, compared with the P&L."""

from django.conf import settings
from django.db import models


class CityBudget(models.Model):
    city = models.ForeignKey("geo.City", on_delete=models.CASCADE, related_name="budgets")
    month = models.DateField()  # the first day of the month
    revenue = models.DecimalField(max_digits=12, decimal_places=2)  # commission + fees
    promotions = models.DecimalField(max_digits=12, decimal_places=2)  # spend limit
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["city", "month"], name="one_budget_per_city_month")
        ]

    def __str__(self) -> str:
        return f"{self.city_id} {self.month:%Y-%m}"
