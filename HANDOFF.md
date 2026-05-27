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
