from django.db import migrations


def add_share(apps, schema_editor):
    from apps.pricing.fare_data import apply_services, load_fares

    RideType = apps.get_model("pricing", "RideType")
    load_fares(apps.get_model("geo", "City"), RideType, apps.get_model("pricing", "FareRule"))
    apply_services(RideType)


class Migration(migrations.Migration):
    dependencies = [("pricing", "0010_fare_rule_auto_paused")]

    operations = [migrations.RunPython(add_share, migrations.RunPython.noop)]
