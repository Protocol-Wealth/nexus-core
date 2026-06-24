# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Monte Carlo decumulation simulation.

Pure, deterministic (given a seed), vectorized over paths. Simulates a
de-identified portfolio drawn down by an annual spend (less guaranteed income)
across ``years``, under one of five return models:

- ``multivariate_normal`` — annual asset returns ~ MVN(means, covariance).
- ``student_t`` — multivariate Student-t (fat tails), scaled to the covariance.
- ``block_bootstrap`` — moving-block resample of the generated return series.
- ``markov_regime`` — regime-switching: a Markov chain over the regime
  transition matrix modulates each year's mean/vol.
- ``emf_regime`` — like markov_regime but anchored on the LIVE current regime
  and scaled by the portfolio's EMF ``lambda`` (regime sensitivity).

The portfolio rebalances annually to its initial blended weights. Withdrawals
are taken at the start of each year (so sequence-of-returns risk bites), then
the remainder grows. A path "fails" once it is depleted. Educational scenario
analysis — not advice, not a projection of any specific person's outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .regime import GENERIC_REGIMES, transition_matrix

_T_DOF = 5.0  # Student-t degrees of freedom
_BLOCK = 4  # moving-block bootstrap block length (years)
_LAMBDA_REF = 0.35  # reference lambda; emf scales regime impact relative to this

#: Per-regime annual mean shift (additive) and volatility multiplier.
_REGIME_MEAN_SHIFT = {
    "expansion": 0.015, "inflationary": -0.010, "deflationary": -0.020,
    "stagflation": -0.030, "crisis": -0.080,
}
_REGIME_VOL_MULT = {
    "expansion": 0.90, "inflationary": 1.10, "deflationary": 1.20,
    "stagflation": 1.30, "crisis": 1.60,
}

_REGIME_AWARE = {"markov_regime", "emf_regime"}


@dataclass(frozen=True)
class GuardrailParams:
    """Guyton-Klinger dynamic-withdrawal (decumulation guardrail) configuration.

    When supplied, the simulation replaces the static ``net_spend_by_year`` draw
    (from the first decumulation year onward) with a path-dependent withdrawal
    governed by the Guyton-Klinger decision rules:

    - **Withdrawal rule (inflation):** raise the prior withdrawal by ``inflation``
      each year, but SKIP that raise in a year following a negative portfolio
      return when the current withdrawal rate already exceeds the path's initial
      rate (``freeze_after_loss``).
    - **Capital-preservation rule (upper guardrail):** if the post-inflation
      withdrawal rate rises more than ``band`` above the initial rate, CUT the
      withdrawal by ``cut`` — suspended in the final ``preservation_final_years``
      years (preservation matters less near the horizon).
    - **Prosperity rule (lower guardrail):** if the rate falls more than ``band``
      below the initial rate, RAISE the withdrawal by ``raise_pct``.

    The guardrails track the NET portfolio withdrawal (spend less guaranteed
    income), measured against each path's own initial withdrawal rate captured
    when decumulation begins. Educational scenario analysis, not advice.
    """

    inflation: float = 0.025
    band: float = 0.20
    raise_pct: float = 0.10
    cut: float = 0.10
    freeze_after_loss: bool = True
    preservation_final_years: int = 15


def _guardrail_step(
    *,
    withdrawal: np.ndarray,
    balance: np.ndarray,
    initial_rate: np.ndarray,
    prev_return: np.ndarray,
    gr: GuardrailParams,
    allow_cut: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One Guyton-Klinger withdrawal update, vectorized across paths.

    Returns ``(new_withdrawal, cut_mask, raise_mask)``. Depleted paths
    (``balance <= 0``) take the path's initial rate so they trigger neither
    guardrail (the path has already failed; its withdrawal is moot).
    """
    safe_balance = np.maximum(balance, 1e-9)
    rate = np.where(balance > 0.0, withdrawal / safe_balance, initial_rate)
    # Withdrawal rule: inflation raise, frozen after a down year if already elevated.
    if gr.freeze_after_loss:
        frozen = (prev_return < 0.0) & (rate > initial_rate)
        grown = np.where(frozen, withdrawal, withdrawal * (1.0 + gr.inflation))
    else:
        grown = withdrawal * (1.0 + gr.inflation)
    new_rate = np.where(balance > 0.0, grown / safe_balance, initial_rate)
    upper = initial_rate * (1.0 + gr.band)
    lower = initial_rate * (1.0 - gr.band)
    cut_mask = (new_rate > upper) & allow_cut
    raise_mask = new_rate < lower
    out = np.where(cut_mask, grown * (1.0 - gr.cut), grown)
    out = np.where(raise_mask, out * (1.0 + gr.raise_pct), out)
    return np.asarray(out, dtype=float), cut_mask, raise_mask


def _portfolio_returns(
    *,
    model: str,
    means: np.ndarray,
    cov: np.ndarray,
    weights: np.ndarray,
    paths: int,
    years: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Return a (paths, years) array of portfolio returns for a non-regime model."""
    if model == "student_t":
        normal = rng.multivariate_normal(np.zeros_like(means), cov, size=(paths, years))
        chi2 = rng.chisquare(_T_DOF, size=(paths, years, 1)) / _T_DOF
        draws = means + normal / np.sqrt(chi2)
        return np.asarray(draws @ weights)
    if model == "block_bootstrap":
        base = rng.multivariate_normal(means, cov, size=(paths, years))
        n_blocks = -(-years // _BLOCK)  # ceil
        starts = rng.integers(0, years, size=(paths, n_blocks))
        idx = (starts[:, :, None] + np.arange(_BLOCK)[None, None, :]) % years
        idx = idx.reshape(paths, n_blocks * _BLOCK)[:, :years]
        resampled = np.take_along_axis(base, idx[:, :, None], axis=1)
        return np.asarray(resampled @ weights)
    # multivariate_normal (default)
    draws = rng.multivariate_normal(means, cov, size=(paths, years))
    return np.asarray(draws @ weights)


def _regime_paths(
    *, start_regime: str, paths: int, years: int, rng: np.random.Generator
) -> np.ndarray:
    """Simulate a (paths, years) integer regime-index array via the transition matrix."""
    regimes = list(GENERIC_REGIMES)
    trans = np.array([[transition_matrix()[a][b] for b in regimes] for a in regimes])
    cum = trans.cumsum(axis=1)
    start = regimes.index(start_regime) if start_regime in regimes else 0
    idx = np.empty((paths, years), dtype=int)
    idx[:, 0] = start
    draws = rng.random((paths, years))
    for year in range(1, years):
        idx[:, year] = (cum[idx[:, year - 1]] < draws[:, year, None]).sum(axis=1).clip(0, 4)
    return idx


def monte_carlo_decumulation(
    *,
    years: int,
    weights: list[float],
    means: list[float],
    vols: list[float],
    lambdas: list[float],
    correlation: list[list[float]],
    initial_balance: float,
    net_spend_by_year: list[float],
    return_model: str,
    paths: int,
    seed: int,
    regime_seed: int,
    current_regime: str,
    current_age: int | None = None,
    guardrails: GuardrailParams | None = None,
) -> dict[str, Any]:
    """Run the decumulation simulation and return the contract response fields.

    When ``guardrails`` is supplied, withdrawals follow the Guyton-Klinger
    decision rules (path-dependent) instead of the static ``net_spend_by_year``
    schedule, and the response gains ``spendingByYear`` percentile bands plus a
    ``guardrailActivity`` summary. Omitted ⇒ the static-withdrawal behavior is
    byte-identical to before.
    """
    w = np.asarray(weights, dtype=float)
    mu = np.asarray(means, dtype=float)
    sigma = np.asarray(vols, dtype=float)
    cov = np.outer(sigma, sigma) * np.asarray(correlation, dtype=float)
    rng = np.random.default_rng(seed)

    base_returns = _portfolio_returns(
        model=return_model, means=mu, cov=cov, weights=w, paths=paths, years=years, rng=rng
    )

    regime_summary: list[str] = []
    if return_model in _REGIME_AWARE:
        regime_idx = _regime_paths(
            start_regime=current_regime, paths=paths, years=years,
            rng=np.random.default_rng(regime_seed),
        )
        regimes = list(GENERIC_REGIMES)
        shifts = np.array([_REGIME_MEAN_SHIFT[r] for r in regimes])[regime_idx]
        vmults = np.array([_REGIME_VOL_MULT[r] for r in regimes])[regime_idx]
        portfolio_lambda = float(w @ np.asarray(lambdas, dtype=float))
        lambda_scale = portfolio_lambda / _LAMBDA_REF if return_model == "emf_regime" else 1.0
        unconditional = float(w @ mu)
        port_returns = unconditional + (base_returns - unconditional) * vmults + shifts * lambda_scale
        regime_summary = [regimes[i] for i in regime_idx[0]]
    else:
        port_returns = base_returns

    net = np.asarray(net_spend_by_year, dtype=float)
    balance = np.full(paths, float(initial_balance))
    # Per-year percentile bands — the projection fan / cone of outcomes. The
    # balance array at each step is the full cross-path distribution; keep
    # p10..p90 each year so a consumer can render the fan, not just the median
    # path. (median_by_year is the p50 band, retained for back-compat.)
    band_pcts = (10, 25, 50, 75, 90)
    bands_by_year = np.empty((years, len(band_pcts)))
    first_depletion_year = np.full(paths, -1, dtype=int)

    # Guyton-Klinger dynamic-withdrawal state (only used when guardrails is set):
    # the first decumulation year is the first positive net draw; from there the
    # withdrawal becomes path-dependent and the static net[year] is ignored.
    gk_start = next((i for i, v in enumerate(net) if v > 0.0), -1) if guardrails else -1
    withdrawal = np.zeros(paths)
    initial_rate = np.zeros(paths)
    prev_return = np.zeros(paths)
    spend_pcts = (10, 50, 90)
    spending_by_year = np.zeros((years, len(spend_pcts)))
    ever_cut = np.zeros(paths, dtype=bool)
    ever_raise = np.zeros(paths, dtype=bool)

    for year in range(years):
        if guardrails is None:
            this_w: float | np.ndarray = net[year]
        elif year < gk_start:  # accumulation (or no decumulation at all)
            this_w = 0.0
        elif year == gk_start:  # capture each path's initial withdrawal rate
            withdrawal = np.full(paths, float(net[gk_start]))
            initial_rate = withdrawal / np.maximum(balance, 1e-9)
            this_w = withdrawal
        else:
            withdrawal, cut_mask, raise_mask = _guardrail_step(
                withdrawal=withdrawal, balance=balance, initial_rate=initial_rate,
                prev_return=prev_return, gr=guardrails,
                allow_cut=(years - year) > guardrails.preservation_final_years,
            )
            ever_cut |= cut_mask
            ever_raise |= raise_mask
            this_w = withdrawal

        balance_before = balance
        balance = (balance - this_w) * (1.0 + port_returns[:, year])
        np.maximum(balance, 0.0, out=balance)
        newly_depleted = (first_depletion_year < 0) & (balance <= 0.0)
        first_depletion_year[newly_depleted] = year
        bands_by_year[year] = np.percentile(balance, band_pcts)
        if guardrails is not None:
            # The realized draw can't exceed what the portfolio held that year.
            effective = np.clip(np.minimum(np.asarray(this_w, dtype=float), balance_before), 0.0, None)
            spending_by_year[year] = np.percentile(effective, spend_pcts)
        prev_return = port_returns[:, year]
    median_by_year = bands_by_year[:, 2] if years > 0 else np.empty(0)

    terminal = balance
    percentiles = np.percentile(terminal, [10, 25, 50, 75, 90])
    failed = first_depletion_year >= 0
    failed_years = first_depletion_year[failed]

    def _percentile_map(values: np.ndarray) -> dict[str, float]:
        if values.size == 0:
            return {}
        pct = np.percentile(values, [10, 50, 90])
        return {f"p{p}": round(float(v), 2) for p, v in zip([10, 50, 90], pct, strict=True)}

    first_decade_years = min(10, years)
    first_decade_returns = np.mean(port_returns[:, :first_decade_years], axis=1)
    survived = terminal > 0.0

    def _median_or_none(values: np.ndarray) -> float | None:
        if values.size == 0:
            return None
        return round(float(np.median(values)), 4)

    depletion_stats: dict[str, Any] = {
        "failedPathCount": int(failed.sum()),
        "failedPathProbability": round(float(np.mean(failed)), 4),
        "depletionYearPercentiles": _percentile_map(failed_years.astype(float)),
    }
    if current_age is not None:
        depletion_stats["depletionAgePercentiles"] = _percentile_map(
            (failed_years + current_age).astype(float)
        )

    response: dict[str, Any] = {
        "successProbability": round(float(np.mean(terminal > 0.0)), 4),
        "terminalValues": {
            f"p{p}": round(float(v), 2) for p, v in zip([10, 25, 50, 75, 90], percentiles, strict=True)
        },
        "medianBalanceByYear": [round(float(v), 2) for v in median_by_year],
        "balancePercentilesByYear": {
            f"p{p}": [round(float(v), 2) for v in bands_by_year[:, i]]
            for i, p in enumerate(band_pcts)
        },
        "depletionStats": depletion_stats,
        "firstDecadeReturnVsOutcome": {
            "years": first_decade_years,
            "successfulMedianAnnualReturn": _median_or_none(first_decade_returns[survived]),
            "failedMedianAnnualReturn": _median_or_none(first_decade_returns[~survived]),
        },
        "worstPathTerminal": round(float(terminal.min()), 2),
        "regimePathSummary": regime_summary,
        "seedUsed": seed,
    }
    if guardrails is not None:
        # The dynamic-withdrawal layer: per-year spending distribution (so the
        # guardrail cuts/raises are visible) + how often the rails bound.
        response["withdrawalRule"] = "guyton_klinger"
        response["spendingByYear"] = {
            f"p{p}": [round(float(v), 2) for v in spending_by_year[:, i]]
            for i, p in enumerate(spend_pcts)
        }
        response["guardrailActivity"] = {
            "pathsWithCut": round(float(np.mean(ever_cut)), 4),
            "pathsWithRaise": round(float(np.mean(ever_raise)), 4),
            "band": guardrails.band,
            "cut": guardrails.cut,
            "raise": guardrails.raise_pct,
        }
    return response


__all__ = ["GuardrailParams", "monte_carlo_decumulation"]
