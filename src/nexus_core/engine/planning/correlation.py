# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Correlation-matrix estimation for planning.

Pure, deterministic math over aligned return series. Two estimators:

- **sample** — the Pearson correlation of the aligned returns.
- **Ledoit-Wolf** — the sample covariance shrunk toward the constant-correlation
  target (Ledoit & Wolf, *Honey, I Shrunk the Sample Covariance Matrix*, J.
  Portfolio Management 2004), then re-expressed as a correlation matrix. The
  shrinkage intensity is estimated from the data and clamped to ``[0, 1]``;
  shrinkage pulls the off-diagonal correlations toward their average, yielding a
  better-conditioned estimate for small samples.

No I/O — callers supply the aligned per-asset return lists. Educational only.
"""

from __future__ import annotations

import numpy as np


def _to_matrix(returns_by_id: dict[str, list[float]]) -> tuple[list[str], np.ndarray]:
    ids = list(returns_by_id)
    rows = [returns_by_id[i] for i in ids]
    lengths = {len(r) for r in rows}
    if len(lengths) != 1:
        raise ValueError("all return series must have the same length (align before estimating)")
    if lengths == {0} or next(iter(lengths)) < 2:
        raise ValueError("need at least 2 aligned observations per series")
    return ids, np.asarray(rows, dtype=float).T  # shape: T observations x N assets


def _ledoit_wolf_constant_correlation(observations: np.ndarray) -> np.ndarray:
    """Return the LW constant-correlation-shrunk covariance of ``observations`` (T x N)."""
    t, n = observations.shape
    x = observations - observations.mean(axis=0)
    sample = (x.T @ x) / t  # MLE sample covariance
    var = np.diag(sample).copy()
    std = np.sqrt(var)
    outer_std = np.outer(std, std)

    # Constant-correlation target: average off-diagonal correlation, same variances.
    corr = sample / outer_std
    rbar = (np.sum(corr) - n) / (n * (n - 1))
    target = rbar * outer_std
    np.fill_diagonal(target, var)

    # pi-hat: sum of asymptotic variances of the sample covariance entries.
    x2 = x**2
    pi_mat = (x2.T @ x2) / t - sample**2
    pi_hat = float(np.sum(pi_mat))

    # rho-hat: diagonal term + the constant-correlation target's off-diagonal term.
    rho_diag = float(np.sum(np.diag(pi_mat)))
    third = (x * x2).T @ x / t  # third_ij = mean_t x_ti^3 x_tj
    theta_ii = third - var[:, None] * sample  # E[(x_i^2 - var_i)(x_i x_j - s_ij)]
    theta_jj = third.T - var[None, :] * sample  # E[(x_j^2 - var_j)(x_i x_j - s_ij)]
    ratio_ji = std[None, :] / std[:, None]  # sqrt(var_j / var_i)
    ratio_ij = std[:, None] / std[None, :]  # sqrt(var_i / var_j)
    off = (rbar / 2.0) * (ratio_ji * theta_ii + ratio_ij * theta_jj)
    np.fill_diagonal(off, 0.0)
    rho_hat = rho_diag + float(np.sum(off))

    gamma = float(np.sum((target - sample) ** 2))
    if gamma == 0.0:
        return np.asarray(sample, dtype=float)
    kappa = (pi_hat - rho_hat) / gamma
    delta = min(1.0, max(0.0, kappa / t))
    shrunk = delta * target + (1.0 - delta) * sample
    return np.asarray(shrunk, dtype=float)


def correlation_matrix(
    returns_by_id: dict[str, list[float]], *, shrinkage: bool
) -> dict[str, dict[str, float]]:
    """Return a symmetric correlation matrix (diagonal 1) keyed by asset id.

    Args:
        returns_by_id: Aligned return series per asset id (equal length, >= 2).
        shrinkage: When ``True``, apply Ledoit-Wolf constant-correlation shrinkage;
            otherwise return the plain sample (Pearson) correlation.

    Raises:
        ValueError: If series are unaligned or too short.
    """
    ids, observations = _to_matrix(returns_by_id)

    if shrinkage and len(ids) > 1:
        cov = _ledoit_wolf_constant_correlation(observations)
        std = np.sqrt(np.diag(cov))
        corr = cov / np.outer(std, std)
    else:
        corr = np.corrcoef(observations, rowvar=False)
        corr = np.atleast_2d(corr)

    np.fill_diagonal(corr, 1.0)
    corr = np.clip(corr, -1.0, 1.0)
    return {
        row_id: {col_id: round(float(corr[i, j]), 6) for j, col_id in enumerate(ids)}
        for i, row_id in enumerate(ids)
    }


__all__ = ["correlation_matrix"]
