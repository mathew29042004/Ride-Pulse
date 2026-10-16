"""Demo: the surge optimiser's recommendation becomes a running A/B test, so the simulator's
riders start filling both arms as soon as it runs."""

from . import services


def seed(log=print) -> dict:
    from apps.intelligence import surge_policy

    result = surge_policy.optimise()
    experiment = surge_policy.propose_experiment(result)
    if experiment is None:
        return {"experiments": 0}
    if experiment.status != "RUNNING":
        services.start(experiment)
    log(f"  A/B test '{experiment.key}' running: {experiment.name}")
    return {"experiments": 1}
