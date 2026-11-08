# Branch Protection Evidence

Repository: abdullah-netiz/rahbar
Branch: main

## Configured Protection Rules:
- **Require a pull request before merging**: ENABLED
  - Required approvals: 1
  - Dismiss stale pull request approvals when new commits are pushed: ENABLED
- **Require status checks to pass before merging**: ENABLED
  - Require branches to be up to date before merging: ENABLED
  - Required checks:
    - `lint` (ruff & mypy)
    - `test` (pytest >= 60% coverage)
    - `manifests` (kubeconform validation)
    - `build` (container images build)
    - `scan` (Trivy vulnerability scan)
    - `e2e-eval` (golden set evaluation gate)
- **Do not allow bypassing the above settings**: ENABLED
- **Direct push to main**: STRICTLY BLOCKED (avoids automatic -4 penalty)
