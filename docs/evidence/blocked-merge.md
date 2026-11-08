# CI Evaluation Gate & Blocked Merge Evidence

This document records the branch protection enforcement, required status checks, and evaluation gate behavior for Pull Request #1 on `https://github.com/abdullah-netiz/rahbar`.

---

## Pull Request Details
- **PR URL**: [https://github.com/abdullah-netiz/rahbar/pull/1](https://github.com/abdullah-netiz/rahbar/pull/1)
- **Title**: `feat: RAHBAR Grounded RAG on Kubernetes`
- **Head Branch**: `dev`
- **Base Branch**: `main`

---

## 1. Gate Failure State (Regression Triggered / Merging Blocked)

When `eval/run_eval.py` detects an evaluation gate failure (or when any required status check fails):
- `recall@5` falls $> 5$ percentage points below baseline (`0.8718`)
- Any must-abstain question is answered from context (`answered_from_context: true`)
- Citation validity falls below $95\%$ (`0.9500`)
- Manifest validation fails strict kubeconform schema checks

### Observed Failure Record: Run #42476348622
- **Workflow Run**: [https://github.com/abdullah-netiz/rahbar/actions/runs/42476348622](https://github.com/abdullah-netiz/rahbar/actions/runs/42476348622)
- **Trigger**: Pull Request #1 to `main`
- **Failing Job**: `manifests (Set up kubeconform)` (Exit code 2)
- **Downstream Gated Jobs**: `build`, `scan`, `e2e-eval` remained pending/skipped due to `needs:` gating.

### GitHub UI State
```
┌────────────────────────────────────────────────────────────────────────┐
│  Merging is blocked                                                    │
│  Required status checks have not passed yet.                           │
│                                                                        │
│  ✕ manifests — Process completed with exit code 2. (Details)           │
│  ✓ lint in 18s (Details)                                               │
│  ✓ test in 33s (Details)                                               │
│  ○ build — Waiting for status to be reported                           │
│  ○ scan — Waiting for status to be reported                            │
│  ○ e2e-eval — Waiting for status to be reported                         │
│                                                                        │
│  [ Merge pull request (Greyed out / Disabled) ]                        │
└────────────────────────────────────────────────────────────────────────┘
```
Branch protection on `main` successfully blocked direct merging into production until all required checks were addressed.

---

## 2. Passing State (Remedy Verified / Merge Unlocked)

Once the pipeline was hardened with retry logic and test verification:
- **Passing Workflow Run**: [https://github.com/abdullah-netiz/rahbar/actions/runs/42476622665](https://github.com/abdullah-netiz/rahbar/actions/runs/42476622665)
- **Trigger**: New commit on `dev` synced to PR #1

### Observed Passing Checks
```
┌────────────────────────────────────────────────────────────────────────┐
│  All checks have passed                                                │
│  6 successful checks                                                   │
│                                                                        │
│  ✓ lint in 14s — ruff and mypy static checks passed                    │
│  ✓ test in 20s — pytest with >= 60% coverage passed                    │
│  ✓ manifests in 8s — kubeconform v1.30.0 schema checks passed          │
│  ✓ build in 52s — container image builds passed                        │
│  ✓ scan in 22s — Trivy vulnerability scan passed                       │
│  ✓ e2e-eval in 10m 8s — Kind cluster e2e evaluation gate passed        │
│                                                                        │
│  [ Merge pull request (Green / Enabled upon partner review) ]          │
└────────────────────────────────────────────────────────────────────────┘
```

The regression gate successfully protected the `main` branch from regressions while allowing validated, green code to merge.
