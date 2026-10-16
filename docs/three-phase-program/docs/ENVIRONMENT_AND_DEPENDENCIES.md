# Environment and Dependency Plan

## Environment A — RESILIANT development (current laptop/workstation)

Purpose: local simulation, tests, evidence analysis, docs, contract validation and fake-backend tests.

- Continue using the project's current `.venv` for its existing supported Python/dependency set.
- Keep CPU mode as the default and all tests offline.
- Avoid adding Isaac SDK, CUDA-specific Torch or ROS packages to this environment.
- Record exact versions from the project dependency files; do not independently upgrade the environment to satisfy Isaac.

## Environment B — Isaac runtime (future, separate and not provisioned here)

Purpose: execute the approved Isaac backend only after Phase III has passed and the user grants explicit authorization.

- Separate environment, separate path, separate lock/config and no reuse of project `.venv`.
- Choose binary, dedicated Python package environment, or institution container according to the actual host and current official docs.
- Keep assets and shader caches outside Git. Store assets locally only after permission/licensing/network/disk checks.
- Preserve the exact simulator version and compatible ROS workspace version if ROS is needed.
- Host-specific paths live in ignored local config, never in a committed example file.

## Environment C — optional Nebius model/job runtime (future, hard opt-in)

- API/client dependencies are lazy or isolated and never required for local tests.
- Provider keys live only in local environment variables or secret storage.
- Use explicit quotas, request limits, timeouts and a no-spend test mode.
- No Serverless Job is launched until permitted by the user/account and a budget/credit ceiling is confirmed.

## Example local variables

```dotenv
# Optional Nebius provider; empty means deterministic offline provider.
NEBIUS_API_KEY=
RESILIANT_LLM_PROVIDER=fixture
RESILIANT_ALLOW_CLOUD_JOBS=false

# Future host-specific values: write these only to an ignored local file.
ISAAC_SIM_PATH=
ISAAC_SIM_VERSION=
RESILIANT_ISAAC_EXECUTION_ENABLED=false
```

Never commit a real key or absolute user/machine path. `RESILIANT_ISAAC_EXECUTION_ENABLED` must stay `false` until a later user-authorized runtime stage.
