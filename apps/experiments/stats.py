"""The statistics behind A/B test results, written out so every number can be explained.

* ``two_proportions``: is the treatment's conversion rate different from control's? A two-sided
  z-test on the pooled proportion, plus a 95% confidence interval for the difference.
* ``welch``: is a per-exposure mean (e.g. revenue) different? Welch's t-test with the normal
  approximation (fine at the sample sizes an experiment needs).
* ``srm``: sample ratio mismatch. If a 50/50 split comes out 56/44, assignment is broken and no
  other result can be trusted; a chi-square test with one degree of freedom catches it.
* ``sample_size``: exposures needed per variant to detect ``minimum_effect`` with 80% power at a
  5% significance level, so a test isn't stopped early on noise.
"""

import math

Z_95 = 1.959964  # two-sided 5%
Z_80 = 0.841621  # 80% power


def normal_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def two_sided_p(z: float) -> float:
    return 2 * (1 - normal_cdf(abs(z)))


def two_proportions(successes_a: int, n_a: int, successes_b: int, n_b: int) -> dict:
    if not n_a or not n_b:
        return {"p_a": None, "p_b": None, "diff": None, "ci": None, "p_value": None}
    p_a, p_b = successes_a / n_a, successes_b / n_b
    pooled = (successes_a + successes_b) / (n_a + n_b)
    se_pooled = math.sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b)) or 1e-12
    z = (p_b - p_a) / se_pooled
    se = math.sqrt(p_a * (1 - p_a) / n_a + p_b * (1 - p_b) / n_b)
    diff = p_b - p_a
    return {
        "p_a": p_a,
        "p_b": p_b,
        "diff": diff,
        "relative": diff / p_a if p_a else None,
        "ci": [diff - Z_95 * se, diff + Z_95 * se],
        "z": z,
        "p_value": two_sided_p(z),
    }


def welch(mean_a: float, var_a: float, n_a: int, mean_b: float, var_b: float, n_b: int) -> dict:
    if n_a < 2 or n_b < 2:
        return {"diff": None, "ci": None, "p_value": None}
    se = math.sqrt(var_a / n_a + var_b / n_b) or 1e-12
    diff = mean_b - mean_a
    t = diff / se
    return {
        "diff": diff,
        "ci": [diff - Z_95 * se, diff + Z_95 * se],
        "t": t,
        "p_value": two_sided_p(t),
    }


def srm(n_a: int, n_b: int, expected_b: float) -> dict:
    """Chi-square test (1 df) of the observed split against the configured one."""
    total = n_a + n_b
    if not total:
        return {"p_value": None, "mismatch": False}
    exp_a, exp_b = total * (1 - expected_b), total * expected_b
    chi2 = (n_a - exp_a) ** 2 / exp_a + (n_b - exp_b) ** 2 / exp_b
    # For 1 df, P(X > chi2) = 2 * (1 - Phi(sqrt(chi2))).
    p = two_sided_p(math.sqrt(chi2))
    return {"chi2": chi2, "p_value": p, "mismatch": p < 0.001}


def sample_size(baseline: float, minimum_effect: float) -> int:
    """Exposures per variant to detect an absolute change of ``minimum_effect``."""
    baseline = min(max(baseline, 0.01), 0.99)
    target = min(max(baseline + minimum_effect, 0.01), 0.99)
    variance = baseline * (1 - baseline) + target * (1 - target)
    return math.ceil((Z_95 + Z_80) ** 2 * variance / (minimum_effect**2))
