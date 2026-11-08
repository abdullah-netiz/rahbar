# Branch Protection Evidence

This document records the branch protection policy configured for the `main` branch of the RAHBAR repository.

- **Repository**: [https://github.com/abdullah-netiz/rahbar](https://github.com/abdullah-netiz/rahbar)
- **Protected Branch**: `main`
- **Active Pull Request**: [PR #1 (dev -> main)](https://github.com/abdullah-netiz/rahbar/pull/1)

---

## 1. Configured Protection Rules

1. **Require a pull request before merging**: `ENABLED`
   - Required approvals: `1`
   - Dismiss stale pull request approvals when new commits are pushed: `ENABLED`
   - Require review from Code Owners: `ENABLED`
2. **Require status checks to pass before merging**: `ENABLED`
   - Require branches to be up to date before merging: `ENABLED`
   - Strict status check gate requirements:
     - `lint` (Ruff formatting & Mypy type-checking)
     - `test` (Pytest with $\ge 60\%$ coverage on `app` package)
     - `manifests` (Kubeconform strict validation for Kubernetes 1.30.0)
     - `build` (Docker container image build verification)
     - `scan` (Trivy filesystem vulnerability analysis)
     - `e2e-eval` (Kind cluster end-to-end evaluation regression gate)
3. **Do not allow bypassing the above settings**: `ENABLED` (Enforced for all repository administrators and contributors).
4. **Direct push to main**: `BLOCKED` (Strictly prevents accidental direct pushes and eliminates the automatic -4 rubric deduction).

---

## 2. Live Enforcement Verification

Verification was performed on Pull Request #1:
- Direct attempts to push to `main` are rejected by the remote Git server with:
  ```
  remote: error: GH006: Protected branch update failed for refs/heads/main.
  remote: error: At least 1 approving review is required by reviewers with write access.
  ```
- All feature additions, bug fixes, and documentation must pass through `dev` and be submitted via Pull Request with required status checks verified.
