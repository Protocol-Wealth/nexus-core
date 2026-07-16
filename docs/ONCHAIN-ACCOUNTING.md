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
The current review status is `pending_governance_review`, so
`completeness.statement_ready` is always `false` even when all calculation facts
are complete. A CIO/IC/CCO methodology review is required before a consumer may
use this output in a client statement. Code review or passing CI does not satisfy
that governance requirement.

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
the matching in leg preserves quantity, unit basis, acquisition date, acquisition
event/transaction lineage, and the source lot reference without realizing gain.
An unmatched inbound transfer may use a manual override only when the caller
asserts same ownership and supplies original basis/date. External, unknown, and
unmatched transfers remain explicit completeness gaps. A market value observed
on transfer never becomes original basis automatically.

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
2. `opening_state`: a `schema_version=1.0.0` snapshot at exactly `start_at - 1`
   second, including unique opaque lot references, account, asset, quantity,
   basis, acquisition date/order, and provenance. Events before the period are
   rejected in this mode to prevent double replay.

Events sharing a timestamp require unique `sequence` values. Opening lots sharing
account, asset, and acquisition time require unique `acquisition_sequence`
values. Event IDs, opening lot refs, override refs, override targets, and as-of
price assets are validated for uniqueness. Replaying identical inputs is
deterministic.

As-of prices are closing valuations, not replayed events. A price timestamped
exactly at `end_at` is accepted; a price after `end_at` is rejected.

## Completeness And Lineage

Open lots carry account, lot, source-lot, acquisition-event, transaction, basis,
and price provenance. Dispositions additionally carry disposal event/transaction,
gross and fee-adjusted proceeds, term, and per-record missing fields.

`coverage` reports known/unknown lot and disposition counts plus unresolved event,
transfer, and fee counts. `completeness.gaps` gives stable codes with opaque event,
account, and asset references. Unknown basis or proceeds stays `null`; it is never
coerced to zero.

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
