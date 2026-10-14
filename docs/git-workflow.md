# Git and release workflow

1. `main` remains runnable and tested.
2. Implement bounded changes on branches such as `feat/simulation-contract`, `feat/llm-hypotheses`, `feat/evidence-validation`, and `feat/isaac-host-export`.
3. Require `ruff check src tests` and `pytest` before merging.
4. Commit dependency/config changes separately from generated experiment output.
5. Never commit `.env`, API tokens, cloud credentials, host secrets, simulator caches or large assets.
6. Every experiment manifest records the Git SHA used to execute it.
7. Tag working releases; for example, `v0.1.0` for the tested surrogate baseline and a later submission-candidate tag when appropriate.
8. Keep the public README aligned with what the code actually does. Future plans belong under “Limitations” or “Next work,” not phrased as completed results.

Suggested commit messages:

- `chore: scaffold reproducible RESILIANT-Z benchmark`
- `feat(sim): add validated simulator result contract`
- `feat(agent): add constrained hypothesis generation`
- `feat(evidence): validate interactions on held-out seeds`
- `feat(policy): add matched-seed replay evaluation`
- `feat(isaac): export real simulator metrics`
- `docs: publish reproduction and limitations`
