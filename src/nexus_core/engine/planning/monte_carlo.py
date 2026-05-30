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
) -> dict[str, Any]:
    """Run the decumulation simulation and return the contract response fields."""
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
    median_by_year = np.empty(years)
    for year in range(years):
        balance = (balance - net[year]) * (1.0 + port_returns[:, year])
        np.maximum(balance, 0.0, out=balance)
        median_by_year[year] = float(np.median(balance))

    terminal = balance
    percentiles = np.percentile(terminal, [10, 25, 50, 75, 90])
    return {
        "successProbability": round(float(np.mean(terminal > 0.0)), 4),
        "terminalValues": {
            f"p{p}": round(float(v), 2) for p, v in zip([10, 25, 50, 75, 90], percentiles, strict=True)
        },
        "medianBalanceByYear": [round(float(v), 2) for v in median_by_year],
        "worstPathTerminal": round(float(terminal.min()), 2),
        "regimePathSummary": regime_summary,
        "seedUsed": seed,
    }


__all__ = ["monte_carlo_decumulation"]
