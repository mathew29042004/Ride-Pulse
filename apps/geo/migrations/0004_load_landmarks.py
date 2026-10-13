from django.db import migrations


def load(apps, schema_editor):
    from apps.geo.city_data import load_landmarks

    load_landmarks(apps.get_model("geo", "City"), apps.get_model("geo", "Landmark"))


class Migration(migrations.Migration):
    dependencies = [("geo", "0003_landmark")]

    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
