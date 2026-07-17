# Onchain Accounting Contract

The onchain-accounting gateway is a read-only calculation surface over
de-identified facts. It does not ingest client identity, map wallets to clients,
prepare tax returns, release statements, or retain books and records. Those
responsibilities remain in the private consumer plane.

## Contract And Governance

Contract `0.2.0` retains the `0.1.0` request fields and result fields while adding
account-scoped lots, lineage, replay bounds, transfer and fee treatments, and
structured completeness. Existing all-event requests remain accepted, but they
carry a `missing_report_window` gap and are not statement-ready.

The calculation methodology is version `2.0.0`. Every result includes its
method version, source, last-verified date, treatment matrix, and review status.
The current review status is `approved`, recording the 2026-07-17 CCO/CIO/CTO
decision to put methodology 2.0/FIFO into operational use. Numerically complete,
bounded results can therefore set `completeness.statement_ready=true`. Private
consumers remain responsible for authenticated client linkage, exact-artifact
provenance, books-and-records retention, and delivery controls; later partner
review is evidence and does not change calculation readiness.

## Transport Profiles

Restricted REST exposes contract discovery plus all handlers at
`/api/accounting/tools`. Native MCP full mode reuses the same handler registry
for `price_history`, `decode_onchain_events`, `compute_cost_basis`, and
`onchain_pnl_report`. The HTTP application injects the same configured price
historian into REST and MCP, so pricing readiness cannot diverge by transport.

Native MCP keeps its existing top-level `describe` tool. Accounting's internal
`describe` handler is not registered under a second or colliding name; the
top-level response reports an `accounting` category and accounting contract
`0.2.0`. The adapter runs the same recursive identity-key scan, maps sanitized
input failures to MCP `ToolError`, and adds the same contract/disclaimer envelope
as REST.

The hosted service runs `NEXUS_PUBLIC_MCP_PROFILE=demo`. MCP demo construction
returns before the accounting registry or historian is attached to MCP, so none
of the accounting tools are publicly exposed there. Full-profile registration
remains read-only and does not move identity, private ingestion, persistence,
approvals, or statement release into this repository.

## Numeric Envelope

All wire-level numeric values are finite decimal strings. Direct quantities and
unit prices allow at most 36 fractional and 42 integer digits. Explicit monetary
totals allow 72 fractional and 84 integer digits so an exact product of two
direct inputs remains representable. Authoritative opening-snapshot basis and
fee values use a bounded 256-fractional/128-integer derived envelope so an engine
output can be replayed in the next statement period. Extreme scientific
exponents, oversized coefficients, NaN, and infinity are rejected before any
accounting arithmetic. Internal exact-sum operations enforce a separate bounded
alignment envelope and return an input error instead of allocating
caller-controlled precision.

Division is method-pinned: calculations use a local 384-digit context,
round-half-even, and at most 256 fractional digits, independent of the caller's
thread-local Decimal context. Proportional lot, fee, transfer, and allocation
shares are additionally clamped to the inclusive range from zero through their
authoritative remaining total; the exact residual is assigned separately. This
prevents a rounded partial share from producing a negative remaining basis.

## Decoder Chain Contract

Each `RawTransactionInput.chain` is the authoritative chain for one transaction.
It is trimmed and normalized to lowercase, every explicit movement asset chain
must match it, and movements without a chain inherit it in the normalized event.
Blank or contradictory chain context is rejected before fallback event identity
or accounting replay can be produced.

## Event Treatment Matrix

| Event kind | Engine treatment |
| --- | --- |
| `acquire` | Opens an account-local lot at supplied market value. |
| `dispose` | Consumes FIFO lots only from `account_ref` and records a disposition. |
| `swap` | Records out legs as dispositions and opens in-leg lots. |
| `claim` | Opens a lot at supplied value; the engine does not calculate income tax. |
| `transfer_in`, `transfer_out` | Requires `transfer_ref` and `transfer_treatment`. |
| `deposit`, `withdraw`, `lp_add`, `lp_remove`, `stake`, `unstake` | Requires caller-reviewed `tax_treatment=taxable_exchange`; otherwise the event remains unresolved and is not calculated. |
| `fee` | Records the explicitly identified fee asset as a separate disposition. |
| `other` | Remains unresolved until classified upstream. |

Direction alone never decides tax treatment. The engine deliberately does not
invent nonrecognition, basis carry, income character, wash-sale, like-kind, gift,
or other tax conclusions for ambiguous events.

## Account And Transfer Isolation

FIFO queues are keyed by `(account_ref, asset_id)`. A disposal in one account can
never consume another account's lot implicitly.

A same-owner transfer requires an opaque `transfer_ref` on both events and
`transfer_treatment=same_owner`. The out leg moves the selected FIFO fragments;
the matching in leg preserves quantity, authoritative remaining basis and fee
basis totals, original unit basis, acquisition date/order, acquisition
event/transaction lineage, and the source lot reference without realizing gain.
Destination queues are re-sorted by original acquisition order, so an older lot
that arrives later by transfer still precedes newer destination lots.
An unmatched inbound transfer may use a manual override only when the caller
asserts same ownership and supplies original basis/date. External, unknown, and
unmatched transfers remain explicit completeness gaps. A market value observed
on transfer never becomes original basis automatically.

If a bounded report ends after a linked same-owner transfer-out but before the
matching transfer-in, the engine records the unmatched transfer gap and returns
all closing-inventory totals as `null`. The in-transit fragments are not assigned
back to the source account or fabricated into a destination account, and their
basis is never misreported as zero.

## Fees

`fee_usd` is no longer ignored. A nonzero fee requires:

- `fee_allocation=acquisition_basis`, `disposition_proceeds`, or an explicit
  `none`; and
- `fee_payment=fiat` or `digital_asset`.

An acquisition allocation increases basis once. A disposition allocation reduces
proceeds once. When a digital asset paid the fee, its out movement must be a
separate `role=fee` leg; the engine also consumes that asset's account-local lot
and records the fee-asset disposition. Missing payment-asset facts or unknown
allocation remain gaps rather than silently disappearing.

A standalone `kind=fee` event remains backward-compatible when it supplies only
asset out legs. When present, its allocation may only be `none`, its payment may
only be `digital_asset`, and a redundant `fee_usd` must equal the priced out
legs. Fiat payment or basis/proceeds allocation on a standalone fee event is
rejected. For a combined transaction, `fee_payment=digital_asset` without its
separate asset out leg is returned as a structured completeness gap.

## Report Replay

Statement-grade calls provide a non-empty, half-open report window
`[start_at, end_at)` and exactly one opening-history source. An event at
`end_at` belongs to the next statement, preventing double-counting across
adjacent periods:

1. `full_history=true`: the caller asserts that all relevant history was
   supplied. Pre-period events build opening lots, in-period dispositions are
   reported, and post-period events are excluded.
2. `opening_state`: a `schema_version=2.0.0` snapshot at exactly `start_at - 1`
   second, with `basis_method=fifo`, `basis_method_version=2.0.0`, and
   `snapshot_complete=true`. It includes unique opaque lot references, account,
   asset, quantity, authoritative remaining total basis/fee basis, original unit
   basis, acquisition date/order/leg index, root lineage, and provenance. Events
   before the period are rejected in this mode to prevent double replay. A
   unit-only legacy lot remains calculable but produces a
   `missing_opening_total_basis` gap. An acquisition-fee basis component cannot
   exceed the effective total cost basis.

A bounded request may contain an empty `events` list. This represents a quiet
period and still returns opening lots, closing valuation, completeness, and a
zero-disposition PnL report. Legacy all-event requests still require an event.

Replayed events sharing a timestamp require unique `sequence` values. Excluded
post-period events do not participate in replay-order validation. Opening lots
sharing an asset and acquisition time require deterministic original ordering:
distinct roots need unique `acquisition_sequence` values, or unique leg indexes
when they came from the same acquisition event. Split fragments of one root may
span accounts only when their acquisition and provenance invariants agree. Event
IDs, opening lot refs, override refs, override targets, and as-of price assets are
validated for uniqueness. Decoder fallback IDs include an available sequence,
and remaining collisions fail closed. Required opaque references and provenance
are trimmed and reject whitespace-only values. Replaying identical inputs is
deterministic.

As-of prices are closing valuations, not replayed events. A price timestamped
exactly at `end_at` is accepted; a price after `end_at` is rejected.

## Completeness And Lineage

Open lots carry account, lot, source-lot, acquisition-event, transaction, basis,
verified evidence or price provenance, authoritative remaining basis, and
conserved fee basis. Dispositions additionally carry the root lot, disposal
event/transaction, gross and fee-adjusted proceeds, term, and per-record missing
fields. Decimal allocation residue is assigned deterministically to the final
component, so disposal basis plus remaining basis reconciles exactly to the
authoritative input total.

`coverage` reports known/unknown lot and disposition counts plus unresolved event,
transfer-reference, and fee counts. `completeness.gaps` gives stable codes with
opaque event, account, and asset references. Unknown basis or proceeds stays
`null`; it is never coerced to zero. Calculation completeness does not by itself
attest that closing inventory valuations are present or suitable for a particular
client deliverable; the private statement composer applies section-specific
realized-PnL and closing-valuation gates.

Realized-PnL aggregates include a disposal whenever its proceeds and basis are
numerically known, even if missing provenance or acquisition-date facts keep the
record incomplete. Such a record still increments `incomplete_count`; without a
known acquisition date its gain is excluded from both the short- and long-term
subtotals. A disposal with unknown proceeds or basis remains excluded from every
numeric aggregate rather than being treated as zero.

The holding-period calculation uses UTC calendar dates. Counting begins after the
acquisition date and includes the disposition date; a disposition is long term
only after the one-year anniversary. This follows the educational summaries in
the [IRS digital-asset FAQs](https://www.irs.gov/individuals/international-taxpayers/frequently-asked-questions-on-digital-asset-transactions)
and [Publication 544](https://www.irs.gov/publications/p544). The engine remains
tax-awareness recordkeeping, not tax advice or tax-return preparation.

## Minimal Full-History Request

```json
{
  "events": [
    {
      "event_id": "event-acquire-1",
      "account_ref": "account-opaque-1",
      "kind": "acquire",
      "timestamp": 1704067200,
      "tx_ref": "transaction-opaque-1",
      "legs": [
        {
          "asset": { "asset_id": "ethereum:asset-1" },
          "direction": "in",
          "amount": "1",
          "usd_value": "100",
          "price_source": "caller_historian",
          "price_as_of": 1704067200
        }
      ]
    }
  ],
  "report_window": {
    "start_at": 1704067200,
    "end_at": 1735689600,
    "full_history": true
  },
  "method": "fifo"
}
```

Opaque references must not contain identity or raw wallet addresses. EVM,
Bitcoin Bech32/legacy, and supported-chain base58 address shapes are rejected in
every account-reference input. Price and transaction data may be public-chain
facts; client assignments and account names must never cross into this repository
or its hosted gateway.
