# Broad search implementation checklist

- [ ] Add platform-level pagination/window support where the live platform exposes it.
- [ ] Remove application-level hard caps that truncate a collector before its configured breadth is reached.
- [ ] Add per-platform discovery diagnostics to the orchestrator log.
- [ ] Keep B2B-Center modern search as the active implementation.
- [ ] Verify Fabrikant search and detail extraction independently.
- [ ] Replace the generic RTS/TMK link-only parser with platform-specific selectors where required.
- [ ] Verify Rosatom search/detail flow.
- [ ] Run one end-to-end multi-platform search and compare result counts with the public platform UIs.
- [ ] Confirm Excel contains all current-run candidates that pass user filters, including previously known tenders.
