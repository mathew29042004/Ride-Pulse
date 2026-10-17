from django.db import migrations


def load(apps, schema_editor):
    from apps.trust.handbook import load

    load(apps.get_model("trust", "HelpArticle"))


class Migration(migrations.Migration):
    dependencies = [("trust", "0004_staff_handbook")]

    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
