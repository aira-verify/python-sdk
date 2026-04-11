# Governance Lifecycle

A single script that walks through every governance primitive Aira ships:

1. Authorize a wire transfer → policy gate runs
2. Notarize the outcome → cryptographic receipt minted
3. Seed a drift baseline → behavioral expectations
4. Run a drift check → KL divergence vs the baseline
5. Seal a compliance bundle → regulator-ready evidence for the last hour
6. (Admin) seal a Merkle settlement → anchor every receipt

Each step prints the relevant ids, signatures, and counts so you can
correlate them against the dashboard (`/dashboard/actions/{id}`,
`/dashboard/compliance`, `/dashboard/drift`, `/dashboard/settlements`).

## Run it

```bash
export AIRA_API_KEY=aira_live_xxxxxxxxxxxxxxxxxxxxxxxxxx
pip install aira-sdk
python demo.py
```

The script is safe to re-run — every step that creates state uses an
`idempotency_key`, so retries return the original resource without
burning an extra operation.
