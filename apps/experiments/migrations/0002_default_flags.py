from django.db import migrations

FLAGS = [
    ("share-rides", "Shared rides (Share): two riders going the same way share one Mini", True, 100),
    ("rider-weather-alerts", "Rain and big-event alerts on the rider Home screen", True, 100),
    ("driver-hot-zones", "'Busy in the next hour' zones in the driver app", True, 100),
]


def add_flags(apps, schema_editor):
    FeatureFlag = apps.get_model("experiments", "FeatureFlag")
    for key, description, enabled, rollout in FLAGS:
        FeatureFlag.objects.get_or_create(
            key=key,
            defaults={"description": description, "enabled": enabled, "rollout_percent": rollout},
        )


class Migration(migrations.Migration):
    dependencies = [("experiments", "0001_initial")]

    operations = [migrations.RunPython(add_flags, migrations.RunPython.noop)]
