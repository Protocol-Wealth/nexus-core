"""Tax-Loss Harvesting.

Implementation of wash-sale-aware tax-loss harvesting.

Algorithmic inspiration (MIT, but ported to our architecture):
- danguetta/rebalancer - https://github.com/danguetta/rebalancer
  Three-step wash-sale-aware TLH:
  1. Select securities per asset class avoiding 30-day wash-sale windows
  2. Decide which tax lots to sell prioritizing loss harvesting
  3. Compute allocation amounts using 'badness score'

Tunable parameters: MAX_LOSS_TO_FORGO, MAX_GAIN_TO_SELL
"""
