from django.db import migrations


def load(apps, schema_editor):
    from apps.pricing.fare_data import load_fares

    load_fares(
        apps.get_model("geo", "City"),
        apps.get_model("pricing", "RideType"),
        apps.get_model("pricing", "FareRule"),
    )


class Migration(migrations.Migration):
    dependencies = [("pricing", "0002_initial"), ("geo", "0002_load_cities")]

    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
