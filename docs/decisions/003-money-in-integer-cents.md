# 003: Money is integer cents

Status: accepted. Issue: #2 (CC1), #11.

CC1 proposed `money` as `{ amount: number, multipleOf: 0.01 }`. Under floating-point division `jsonschema` rejects
19.99 and 0.07 as multiples of 0.01, and JavaScript computes 0.07 / 0.01 as 7.000000000000001, so ordinary prices
would fail validation in some implementations and pass in others.

1. **The choice.** `money` is `{ cents: integer >= 0, currency: "USD" }`, for example a $129.00 rain shell is
   `{ "cents": 12900, "currency": "USD" }`. Integers are exact in Python, Swift and JavaScript, so every node sums a
   basket the same way. Rejected: decimals without the `multipleOf` check (rounding moves into every implementation).
2. **What it costs.** Every display divides by 100, and SPEC examples written as `amount: 120.00` read differently
   from the documents.
3. **When to revisit.** A second currency, or a currency without two minor units.

Contract change: version 0.1.0 (`$defs/money` in `contracts/schemas/common.schema.json`).
