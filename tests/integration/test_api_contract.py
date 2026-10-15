"""The API contract: the live schema must not break clients built against the snapshot."""

import copy

import pytest

from apps.reliability import contract

pytestmark = pytest.mark.django_db


@pytest.fixture(scope="module")
def schemas(django_db_blocker):
    with django_db_blocker.unblock():
        return contract.load(), contract.generate()


def test_no_breaking_changes_against_the_committed_snapshot(schemas):
    snapshot, live = schemas
    problems = contract.breaking_changes(snapshot, live)
    assert not problems, (
        "Breaking API changes (version the endpoint instead, or run "
        "`manage.py api_contract --update` if this is deliberate):\n" + "\n".join(problems)
    )


def _component(schema, name):
    return schema["components"]["schemas"][name]


def test_the_checker_catches_each_kind_of_break(schemas):
    _, live = schemas
    base = copy.deepcopy(live)

    removed_path = copy.deepcopy(base)
    removed_path["paths"].pop("/api/v1/trips/active/")
    assert any("endpoint removed" in p for p in contract.breaking_changes(base, removed_path))

    trip = _component(base, "Trip")
    field = next(iter(trip["properties"]))
    dropped_field = copy.deepcopy(base)
    _component(dropped_field, "Trip")["properties"].pop(field)
    assert any(
        f"'{field}' was removed" in p for p in contract.breaking_changes(base, dropped_field)
    )

    retyped = copy.deepcopy(base)
    _component(retyped, "Trip")["properties"]["trip_number"] = {"type": "integer"}
    assert any(
        "changed type string → integer" in p for p in contract.breaking_changes(base, retyped)
    )

    stricter = copy.deepcopy(base)
    request = _component(stricter, "TripRequestRequest")
    request.setdefault("required", []).append("promo_code")
    assert any(
        "'promo_code' is now required" in p for p in contract.breaking_changes(base, stricter)
    )


def test_additions_are_not_breaking(schemas):
    _, live = schemas
    base = copy.deepcopy(live)
    grown = copy.deepcopy(base)
    _component(grown, "Trip")["properties"]["new_shiny_field"] = {"type": "string"}
    grown["paths"]["/api/v1/brand-new/"] = {"get": {"responses": {"200": {}}}}
    assert contract.breaking_changes(base, grown) == []
