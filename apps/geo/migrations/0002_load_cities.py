from django.db import migrations


def load(apps, schema_editor):
    from apps.geo.city_data import load_cities

    load_cities(apps.get_model("geo", "City"), apps.get_model("geo", "Zone"))


class Migration(migrations.Migration):
    dependencies = [("geo", "0001_initial")]

    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
