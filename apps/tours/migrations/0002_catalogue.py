from django.db import migrations


def load(apps, schema_editor):
    from apps.tours.catalogue import load

    load(apps.get_model("geo", "City"), apps.get_model("tours", "TourPackage"),
         apps.get_model("tours", "TourStop"))


class Migration(migrations.Migration):
    dependencies = [("tours", "0001_initial"), ("geo", "0005_south_india_cities")]

    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
