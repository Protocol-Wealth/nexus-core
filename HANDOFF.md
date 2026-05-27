# HANDOFF — `nexus-core` (open-source repo)

Cross-repo wiring the parallel private-estate session must pick up. This file
tracks open work that crosses the public/private boundary, so it lives in the
public tree where both sessions can see it.

Branch: `feat/cfp-governance-hardening`
Most recent commit at last update: see `git log -3` on the branch.

---

## Tier 1 — governance parity confirmation (CFP-substrate iteration)

**Status: shipped to the feature branch as of 2026-05-27, pending operator
go/no-go review before any push to `main` or any Tier-2 work begins.**

### What changed in this repo

- `CHANGELOG.md` — `[Unreleased]` entry under "Changed" recording the
  cross-repo governance-parity work performed alongside `pwos-core`. No
  other file in this repo was modified.
- **Confirmed existing**: `CONTRIBUTING.md`, `SECURITY.md`,
  `CODE_OF_CONDUCT.md`, `CHANGELOG.md` already match the canonical PW
  open-source shape (this repo was the source-of-truth that `pwos-core`'s
  parallel hardening copied from). No new governance files written.

### Cross-repo wiring required from the private-estate session

- **(governance-doc consistency check)** Same item as `pwos-core/HANDOFF.md`:
  open `shared/docs/compliance/opensource-policy.md` (private estate
  canonical) and cross-check the license / patent / OIN posture and the
  open-vs-private boundary description against the updated `pwos-core`
  wording. `nexus-core` already states this boundary in its `## What's Open
  vs Private` README section (no change needed here) and continues to
  follow the patent-doc-rule discipline (USPTO #64/034,229; OIN member).
- **(no production code wiring required for Tier 1)** Documentation-only.
  The `nexusmcp.site` deployment running `nexus_core.app` is unaffected;
  no module imports changed, no public API moved, no signal / threshold /
  decay-constant value was added or modified.

### Operator decision required before Tier 2

Tier 2 here is the flagship pair (score-explainability extension + `as_of`
deterministic replay + cross-link doc to pwos-core disclosure schema).
**Not yet authorized.** This session will not begin Tier 2 work until
the operator explicitly says "go."

If Tier 2 is authorized, the private-estate wiring will be (preview, not
committed):

- Surface the new `explanation` object (Tier-2 N2) — per-check pass/fail
  + normalized signal contributions, **shape only, no constant values** —
  in the client-facing research rendering inside pw-os-v2 and
  pw-portal-v2. The narrative-pipeline consumer in the private estate
  should pull `explanation.checks_passed` / `explanation.checks_failed`
  / `explanation.confidence_tier` rather than relying on the old
  free-text `notes` field.
- Make the private-estate research jobs idempotent by passing the new
  `as_of` parameter (Tier-2 N3) on every regime / scoring call. Frozen
  inputs → identical outputs; useful for reproducibility under SEC exam
  conditions and for the audit trail's hash-chain stability.
- Cross-link doc (Tier-2 N4) shows how a `nexus-core` scoring result
  populates the `pwos-core` disclosure-card `knownLimitations[]` field
  conceptually. No code coupling between the repos — the worked example
  is text only.

These three items will only show up here as concrete wiring instructions
after the Tier-2 code lands on this branch. If Tier 2 is declined, this
HANDOFF stays Tier-1-only.

---

## Tier 2 — explainability + deterministic replay + cross-link (CFP-substrate iteration)

**Status: shipped to the feature branch as of 2026-05-27.** Operator
authorized Tier 2 immediately after the Tier-1 checkpoint.

### What landed in this repo (Tier 2)

- **`src/nexus_core/engine/scoring/explanation.py`** — N2: new module
  with `ScoreExplanation`, `CheckExplanation`, `SignalContribution`, and
  `build_score_explanation()`. The explanation is **sanitized by
  construction**: `SignalContribution` carries only `(name, status,
  supports_regime)` — NO `current_value`, NO `threshold_info`, NO
  numeric cutoff. The shape lets a downstream consumer render an
  explanation surface without leaking the operator's production
  threshold values.
- **`src/nexus_core/engine/scoring/framework.py`** — N2 + N3:
  - `ScoreResult` gained two fields: `as_of: date | None = None` and
    `explanation: ScoreExplanation | None = None`. Both default to None
    for backward compat.
  - `ScoringFramework.score(ctx, *, subject=None, as_of=None)` —
    new `as_of` keyword param; the score auto-populates the
    `explanation` and echoes `as_of` onto the result.
  - `to_dict()` now serializes both new fields.
- **`src/nexus_core/engine/scoring/__init__.py`** — re-exports the new
  explanation symbols under `__all__`.
- **`src/nexus_core/engine/regime/signals.py`** — N3: `RegimeResult`
  gained `as_of: date | None = None`; `to_dict()` emits the ISO date
  when set (omits when None).
- **`src/nexus_core/engine/regime/classifier.py`** — N3:
  `RegimeClassifier.classify(..., as_of=None)` — accepts `as_of`,
  echoes it onto the result. The classifier itself is unchanged
  (still pure on signals); `as_of` is metadata for reproducible replay.
- **`src/nexus_core/engine/regime/engine.py`** — N3:
  - `RegimeEngine.fetch_signals(*, force_refresh=False, as_of=None)`
    — when `as_of` is set, bypasses the cache and forwards to the
    underlying `SignalFetcher.fetch(as_of=...)` if the fetcher accepts
    it (TypeError fallback to plain `.fetch()` for providers without
    `as_of` support).
  - `RegimeEngine.classify(signals=None, *, prediction_market=None,
    as_of=None)` — forwards `as_of` to `fetch_signals` and the
    classifier.
- **`tests/test_explanation.py`** — N2 tests. The load-bearing test is
  `test_signal_contributions_strip_threshold_and_raw_value` which
  asserts that serialized contributions have ONLY the three sanitized
  keys (`name`, `status`, `supports_regime`).
- **`tests/test_replay.py`** — N3 tests. Asserts identical results
  across repeated calls with the same `as_of` (classifier + scoring
  framework both), and that `as_of` round-trips through `to_dict()`.
- **`examples/deterministic_replay.py`** — runnable worked example.
  Builds synthetic signals, classifies twice with the same `as_of`,
  asserts the JSON-serialized outputs are byte-identical. Zero data
  dependencies — no network, no API keys.
- **`docs/CROSS-LINK-PWOS-CORE.md`** — N4: conceptual note documenting
  three join points between `nexus-core` and `pwos-core`:
  - `ScoreExplanation` → `DisclosureCard.knownLimitations[]`
  - `as_of` + provenance hash-chain → `DisclosureCard.auditTrail`
  - HITL gate enforcement → `DisclosureCard.humanOversight`

### Cross-repo wiring required from the private-estate session (Tier 2)

The wiring contract for these items lives in `pwos-core/HANDOFF.md`
under "Cross-repo wiring required from the private-estate session
(Tier 2)" — that is the authoritative source. The two items most
specifically tied to *this* repo's surface:

- **Consume `score_result.explanation.*` instead of re-deriving from
  `score_result.checks`** in any client-facing narrative path. The
  sanitized contract is the safer surface for client copy because it
  cannot accidentally leak the operator's production threshold
  numbers.
- **Thread `as_of: date` through the audit-trail replay code path.**
  The new fields are backward-compatible — existing call sites that
  don't pass `as_of` keep working — but every replay-context call site
  should pass it so the result is reproducible from a frozen snapshot
  and the provenance hash-chain (`@protocolwealthos/shared/provenance`)
  carries the as-of in the hashed content.

### Public-surface compatibility

- Every new field on `RegimeResult` and `ScoreResult` defaults to
  `None`. Pre-Tier-2 callers continue to compile + work without
  changes.
- `to_dict()` shape is additive — pre-existing keys retained, new
  keys (`as_of`, `explanation`) appear only when set / non-None.
- No symbol renamed. No symbol removed. No regime taxonomy change. No
  new threshold value added or modified.

---

## Build + test status at last update

Captured in the checkpoint summary on this branch. If the operator wants
to re-verify before approving the push to `main`, from the repo root with
the `.venv` activated:

```bash
pip install -e ".[dev]"     # if not already installed
pytest
ruff check src/ tests/
mypy src/nexus_core/
```

All three should be green; this iteration touched no code paths.
