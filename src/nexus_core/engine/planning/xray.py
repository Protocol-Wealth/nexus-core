# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Portfolio X-ray — regime-aware structural diagnostics (educational).

Reads a de-identified portfolio (blended asset-class weights + per-asset
expected return / volatility / EMF λ, plus the account-type balance mix) and
returns a structured set of *findings* — concentration, diversification,
account / tax-location spread, and — the differentiator — **regime sensitivity
conditioned on the LIVE macro regime** (a high portfolio λ in an adverse regime
is flagged). Inspired by portfolio "X-ray" rule engines, but anchored on the EMF
regime rather than generic rules.

Pure and deterministic — no I/O, no market data, no client context; the caller
supplies clean numeric inputs (the tool layer validates + blends) and the live
regime. Documented simplifications (planning illustration, not advice):
``weightedAvgVolatility`` is the weight-weighted average asset vol — it ignores
diversification (correlations), so it is an upper bound, not the true portfolio
volatility; concentration uses the Herfindahl index over the blended weights.
"""

from __future__ import annotations

from typing import Any, Literal

Severity = Literal["info", "warn", "alert"]

#: Single-asset weight thresholds for the concentration finding.
_CONCENTRATION_ALERT = 0.60
_CONCENTRATION_WARN = 0.40
#: Portfolio-λ thresholds (regime sensitivity), applied in an adverse regime.
_LAMBDA_ALERT = 0.30
_LAMBDA_WARN = 0.15
#: Asset volatility at/above which an asset counts toward the "growth sleeve".
_GROWTH_VOL = 0.12
#: An account type holding at least this share is "tax-location concentrated".
_ACCOUNT_CONCENTRATION = 0.90
#: Regimes where regime sensitivity is most consequential.
_ADVERSE_REGIMES = frozenset({"crisis", "stagflation", "deflationary"})


def _finding(fid: str, severity: Severity, title: str, detail: str) -> dict[str, str]:
    return {"id": fid, "severity": severity, "title": title, "detail": detail}


def portfolio_xray(
    *,
    asset_ids: list[str],
    weights: list[float],
    means: list[float],
    vols: list[float],
    lambdas: list[float],
    account_balances: dict[str, float],
    regime: str,
) -> dict[str, Any]:
    """Structural + regime-conditioned diagnostics for a de-identified portfolio.

    Args:
        asset_ids: Asset-class ids (aligned with the numeric lists below).
        weights: Blended portfolio weights per asset (sum ~ 1).
        means / vols / lambdas: Per-asset expected return, volatility, EMF λ.
        account_balances: Balance by account type (``taxable`` / ``traditional``
            / ``roth``); used for the tax-location finding.
        regime: The live generic macro regime (the tool injects it).

    Returns:
        Portfolio-level metrics (``weightedExpectedReturn``, ``weightedAvgVolatility``,
        ``concentration`` {maxWeight, maxWeightAsset, herfindahl, effectiveHoldings},
        ``portfolioLambda``, ``growthAllocation``, ``accountMix``) plus a
        ``regime`` echo and a list of ``findings`` ({id, severity, title, detail}).
    """
    n = len(asset_ids)
    if not (n == len(weights) == len(means) == len(vols) == len(lambdas)):
        raise ValueError("asset_ids, weights, means, vols, lambdas must align")
    if n == 0:
        raise ValueError("portfolio must have at least one asset class")

    w_exp_return = sum(w * m for w, m in zip(weights, means, strict=True))
    w_avg_vol = sum(w * v for w, v in zip(weights, vols, strict=True))
    portfolio_lambda = sum(w * lam for w, lam in zip(weights, lambdas, strict=True))
    growth_alloc = sum(w for w, v in zip(weights, vols, strict=True) if v >= _GROWTH_VOL)

    herfindahl = sum(w * w for w in weights)
    effective_holdings = 1.0 / herfindahl if herfindahl > 0 else 0.0
    max_i = max(range(n), key=lambda i: weights[i])
    max_weight = weights[max_i]
    max_asset = asset_ids[max_i]

    total_balance = sum(account_balances.values())
    account_mix = {
        t: round(account_balances.get(t, 0.0) / total_balance, 4) if total_balance > 0 else 0.0
        for t in ("taxable", "traditional", "roth")
    }

    findings: list[dict[str, str]] = []

    # 1. Concentration (single asset + effective holdings).
    if max_weight >= _CONCENTRATION_ALERT:
        sev: Severity = "alert"
    elif max_weight >= _CONCENTRATION_WARN:
        sev = "warn"
    else:
        sev = "info"
    findings.append(
        _finding(
            "concentration",
            sev,
            "Single-asset concentration",
            f"{max_asset} is {max_weight:.0%} of the portfolio; "
            f"effective holdings ≈ {effective_holdings:.1f}.",
        )
    )

    # 2. Regime sensitivity (the differentiator) — conditioned on the live regime.
    adverse = regime in _ADVERSE_REGIMES
    if adverse and portfolio_lambda >= _LAMBDA_ALERT:
        rsev: Severity = "alert"
        rmsg = "Elevated regime sensitivity for the current regime"
    elif adverse and portfolio_lambda >= _LAMBDA_WARN:
        rsev = "warn"
        rmsg = "Moderate regime sensitivity for the current regime"
    else:
        rsev = "info"
        rmsg = (
            "Regime sensitivity is modest"
            if adverse
            else "Benign regime — regime sensitivity is less pressing"
        )
    findings.append(
        _finding(
            "regime_sensitivity",
            rsev,
            rmsg,
            f"Current regime is {regime}; portfolio EMF λ = {portfolio_lambda:.2f} "
            f"(higher λ = more sensitive to a regime shift).",
        )
    )

    # 3. Tax-location diversification.
    if total_balance > 0:
        top_type, top_share = max(account_mix.items(), key=lambda kv: kv[1])
        tsev: Severity = "warn" if top_share >= _ACCOUNT_CONCENTRATION else "info"
        title = (
            "Limited tax-location diversification"
            if top_share >= _ACCOUNT_CONCENTRATION
            else "Tax-location spread"
        )
        findings.append(
            _finding(
                "tax_location",
                tsev,
                title,
                f"Taxable {account_mix['taxable']:.0%} · "
                f"Traditional {account_mix['traditional']:.0%} · "
                f"Roth {account_mix['roth']:.0%}.",
            )
        )

    # 4. Growth posture (vol proxy — no equity/bond classifier needed).
    findings.append(
        _finding(
            "growth_posture",
            "info",
            "Growth posture",
            f"Growth sleeve ≈ {growth_alloc:.0%} (assets with volatility ≥ "
            f"{_GROWTH_VOL:.0%}); weighted expected return {w_exp_return:.1%}.",
        )
    )

    return {
        "regime": regime,
        "weightedExpectedReturn": round(w_exp_return, 4),
        "weightedAvgVolatility": round(w_avg_vol, 4),
        "portfolioLambda": round(portfolio_lambda, 4),
        "growthAllocation": round(growth_alloc, 4),
        "concentration": {
            "maxWeight": round(max_weight, 4),
            "maxWeightAsset": max_asset,
            "herfindahl": round(herfindahl, 4),
            "effectiveHoldings": round(effective_holdings, 2),
        },
        "accountMix": account_mix,
        "findings": findings,
    }


__all__ = ["portfolio_xray"]
