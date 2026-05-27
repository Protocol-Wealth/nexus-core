# Cross-link — `nexus-core` ↔ `pwos-core` disclosure card

This note shows how a `nexus-core` regime + scoring output **conceptually**
populates the `pwos-core` disclosure-card model. The two repos do not
depend on each other at the code level. This file exists so an adopter
reading either repo can see the join.

- This repo: [`Protocol-Wealth/nexus-core`](https://github.com/Protocol-Wealth/nexus-core) — regime + scoring engine (Python).
- Sibling: [`Protocol-Wealth/pwos-core`](https://github.com/Protocol-Wealth/pwos-core) — TypeScript compliance primitives, including `@protocolwealthos/shared/disclosure` (the disclosure card).

Both are Apache 2.0 + defensive-patent. Both ship reference / placeholder
configuration; an adopter's production thresholds and policy bindings live
in the adopter's private estate.

---

## The boundary

`nexus-core` decides *which regime is in force* and *how durable an asset
is under that regime*. It emits a `RegimeResult` and a `ScoreResult`. Each
result carries enough structure for a downstream consumer to render an
explanation — but `nexus-core` does NOT decide what disclosure language to
publish about that decision. That belongs to the operator (an RIA's CCO
review) and lives in `pwos-core`'s disclosure-card surface.

`pwos-core` decides *how to describe* the AI-assisted system to the world:
which model is in use, what data-retention posture applies, what human
oversight gates client-facing actions, what the system's known limitations
are, what regulatory rules the operator is operating under. The
`DisclosureCard` (`@protocolwealthos/shared/disclosure`) is the
machine-readable surface for that description.

Wiring them together is an adopter responsibility. The two suggested join
points are below.

---

## Join point 1: `ScoreExplanation` → `DisclosureCard.knownLimitations[]`

`nexus-core/src/nexus_core/engine/scoring/explanation.py` produces a
`ScoreExplanation` that contains, for every scoring run:

- `pass_share` (0..1) — proportion of checks that passed.
- `checks_failed: list[str]` — names of checks that came in below threshold.
- `checks_not_evaluated: list[str]` — names of checks where data was missing.
- `confidence_tier: str` — string form of `ConfidenceTier` (e.g.
  `"HIGH CONFIDENCE"`, `"MODERATE CONFIDENCE"`, `"LOW CONFIDENCE"`,
  `"BELOW THRESHOLD"`, `"NOT APPLICABLE"`).
- `per_check: list[CheckExplanation]` — per-check `signal` + short `summary`,
  with no threshold values.
- `regime_signal_contributions: list[SignalContribution]` — per-regime-signal
  `name` + `status` + `supports_regime`, again with no threshold values.

When an adopter's disclosure card describes the AI-assisted system's
*known limitations*, that list should be enriched (CONCEPTUALLY — by the
adopter's own code) from observed properties of recent scoring runs:

| Observed property in `ScoreExplanation`                         | Suggested `DisclosureCard.knownLimitations[]` entry                                                                 |
|------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------|
| `checks_not_evaluated` non-empty for >X% of recent runs           | "The scoring engine routinely runs with one or more checks unevaluated due to upstream data gaps."                  |
| `confidence_tier` is `"BELOW THRESHOLD"` for the majority of recent runs | "Most current outputs fall below the framework's confidence threshold; treat as research signal, not as recommendation." |
| `regime_signal_contributions` empty (regime input not threaded)   | "The scoring decision is not regime-aware in the current deployment."                                                |
| A specific check consistently appears in `checks_failed`          | "The `<check_name>` dimension has been below threshold in recent periods; weigh accordingly."                        |

**The disclosure card is the CCO-reviewed published artifact, not the raw
explanation.** Don't pipe explanation text directly into the
`knownLimitations[]` field; let the CCO write the human-readable
limitation language, informed by the structural signal the
`ScoreExplanation` provides.

---

## Join point 2: `as_of` + provenance → `DisclosureCard.auditTrail`

Both `RegimeResult` and `ScoreResult` now carry an `as_of: date | None`
field (Tier-2 N3). When set, the call is reproducible from frozen inputs:
the same `signals` + same `as_of` produce the same `RegimeResult`; the
same `ctx` + same `as_of` produce the same `ScoreResult` (and the same
`ScoreExplanation`). This is the property an SEC exam workflow needs:
the operator can show that any classification or score that landed in a
client deliverable can be re-derived from the snapshot of data that
existed at that point in time.

That replayability shape lines up with `DisclosureCard.auditTrail.tamperEvident`
(in pwos-core's disclosure card). Two suggested integrations:

1. **Hash each `as_of` run's output** with
   `@protocolwealthos/shared/provenance` and chain the hash into the
   audit trail. `verifyChain` will then detect any after-the-fact edit to a
   historical classification.

2. **Set `auditTrail.tamperEvident: true`** in the disclosure card only
   once the adopter has actually wired the provenance hash-chain in
   production. The honest-disclosure default is `false` — flip to `true`
   only when verified.

---

## Join point 3: HITL gate → `DisclosureCard.humanOversight`

`pwos-core/packages/shared/src/hitl/` ships a fail-closed HITL gate with
two default action classes:

- `client_facing_deliverable` → `mandatory` approval
- `internal_research`         → `optional` approval

When the adopter's tool orchestrator routes a `nexus-core` scoring output
into a *client-facing* deliverable (a portfolio review PDF, an advice
narrative, a recommendation email), that route should pass through the
HITL gate's `evaluateHitl` against the `client_facing_deliverable` action
class, and the advisor's explicit approval should land in the
provenance-chain record as the `approver` field
(`@protocolwealthos/shared/provenance`'s `ProvenanceApprover`).

Then the disclosure card's `humanOversight` block reflects what's
actually enforced:

- `tier: "human_in_the_loop"` (the strictest of the three shipped tiers)
- `clientFacingRequiresApproval: true`
- `scope: "All client-facing deliverables require explicit advisor approval before delivery. Internal research scratchpads do not require approval."`

The disclosure card's published values must NOT outrun the production
enforcement: if the HITL gate is not wired in the adopter's
orchestrator, the published `clientFacingRequiresApproval` value must be
`false`, even if the operator would prefer to publish `true` for
marketing reasons. The CI gate `assertNoVerifyMarkers` (also in
`@protocolwealthos/shared/disclosure`) is one place an adopter can wire
a build-time check that disclosure-vs-reality stays aligned.

---

## What this doc is NOT

- It is **not** a code-level integration between the two repos.
- It is **not** a contract: each repo's surface evolves independently
  under its own SemVer + changeset discipline.
- It is **not** a CCO-reviewed disclosure template. Adopters' published
  disclosure cards are their own responsibility; this note shows the
  shape, not the content.

When the operator's production wiring lands these joins, the relevant
text will move from this conceptual note to an honest in-repo example.
