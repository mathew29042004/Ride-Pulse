"""Demo-data commands refuse to run outside demo mode."""

import pytest
from django.core.management import CommandError, call_command

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("command", ["seed_demo", "grow_network", "generate_history", "simulate"])
def test_demo_commands_need_demo_mode(settings, command):
    settings.DEMO_MODE = False
    with pytest.raises(CommandError, match="only runs in demo mode"):
        call_command(command)
