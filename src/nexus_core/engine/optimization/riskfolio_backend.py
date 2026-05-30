# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Riskfolio-Lib backend — risk parity, hierarchical risk parity with
richer risk measures, and CVaR-flavored optimization that PyPortfolioOpt
doesn't cover natively.

PyPortfolioOpt remains the primary backend for MVO / max-Sharpe /
min-volatility / Black-Litterman / discrete allocation. Riskfolio-Lib
handles the long tail (24 risk measures, factor-RC constraints,
worst-case MV, EVaR / RLVaR / CDaR / EDaR).

Lazy import — calling these functions requires the optional
``[optimization]`` extra to be installed.

Attribution:
    Riskfolio-Lib — Copyright (c) 2020-2026 Dany Cajas (BSD-3).
    https://github.com/dcajasn/Riskfolio-Lib
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class RiskfolioNotInstalledError(RuntimeError):
    """Raised when Riskfolio-Lib is missing."""


def _require_riskfolio() -> Any:
    try:
        import riskfolio as rp

        return rp
    except ImportError as exc:
        raise RiskfolioNotInstalledError(
            "Riskfolio-Lib not installed. Install with: pip install nexus-core[optimization]"
        ) from exc


@dataclass(frozen=True)
class RiskfolioResult:
    """Outcome of a Riskfolio optimization run.

    Mirrors the shape of PyPortfolioOpt's ``OptimizationResult`` for
    drop-in dispatcher compatibility.
    """

    weights: dict[str, float]
    method: str
    risk_measure: str
    expected_return: float | None = None
    expected_risk: float | None = None
    metadata: dict[str, Any] | None = None


def risk_parity(
    returns: Any,  # pd.DataFrame[date, ticker] of period returns
    *,
    risk_measure: str = "MV",
    method_mu: str = "hist",
    method_cov: str = "ledoit",
    rf: float = 0.0,
) -> RiskfolioResult:
    """Risk-parity allocation — equal risk contribution across assets.

    Args:
        returns: Pandas DataFrame of period returns, columns=tickers.
        risk_measure: Risk-measure code accepted by Riskfolio-Lib.
            Common: ``MV`` (variance), ``CVaR`` (Conditional VaR),
            ``CDaR`` (Conditional Drawdown), ``MAD`` (mean absolute
            deviation), ``EVaR`` (Entropic VaR).
        method_mu: Expected-returns estimator (``hist`` / ``ewma1`` / ...).
        method_cov: Covariance estimator (``hist`` / ``ledoit`` / ``oas`` / ...).
    """
    rp = _require_riskfolio()
    port = rp.Portfolio(returns=returns)
    port.assets_stats(method_mu=method_mu, method_cov=method_cov)
    weights_df = port.rp_optimization(
        model="Classic", rm=risk_measure, rf=rf, b=None, hist=True
    )
    weights = {ticker: float(w) for ticker, w in weights_df.iloc[:, 0].items()}
    return RiskfolioResult(
        weights=weights,
        method="risk_parity",
        risk_measure=risk_measure,
        metadata={"method_mu": method_mu, "method_cov": method_cov},
    )


def hierarchical_risk_parity(
    returns: Any,
    *,
    risk_measure: str = "MV",
    linkage: str = "single",
    codependence: str = "pearson",
) -> RiskfolioResult:
    """HRP via Riskfolio's ``HCPortfolio`` (richer risk measures than
    PyPortfolioOpt's HRPOpt — supports CVaR / CDaR / etc.).

    Args:
        returns: Period-return DataFrame.
        risk_measure: ``MV`` / ``CVaR`` / ``CDaR`` / ``MAD`` / ``MSV`` / etc.
        linkage: Hierarchical clustering linkage method.
        codependence: ``pearson`` / ``spearman`` / ``abs_pearson`` / ...
    """
    rp = _require_riskfolio()
    hcp = rp.HCPortfolio(returns=returns)
    weights_df = hcp.optimization(
        model="HRP",
        codependence=codependence,
        rm=risk_measure,
        linkage=linkage,
        leaf_order=True,
    )
    weights = {ticker: float(w) for ticker, w in weights_df.iloc[:, 0].items()}
    return RiskfolioResult(
        weights=weights,
        method="hrp",
        risk_measure=risk_measure,
        metadata={"linkage": linkage, "codependence": codependence},
    )


def min_cvar(
    returns: Any,
    *,
    alpha: float = 0.05,
    method_mu: str = "hist",
    method_cov: str = "ledoit",
) -> RiskfolioResult:
    """Mean-CVaR efficient frontier minimization at confidence ``alpha``."""
    rp = _require_riskfolio()
    port = rp.Portfolio(returns=returns)
    port.assets_stats(method_mu=method_mu, method_cov=method_cov)
    port.alpha = alpha
    weights_df = port.optimization(
        model="Classic", rm="CVaR", obj="MinRisk", rf=0.0, l=0, hist=True
    )
    weights = {ticker: float(w) for ticker, w in weights_df.iloc[:, 0].items()}
    return RiskfolioResult(
        weights=weights,
        method="min_cvar",
        risk_measure="CVaR",
        metadata={"alpha": alpha},
    )
