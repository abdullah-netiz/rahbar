# CI Evaluation Gate & Blocked Merge Evidence

## Pull Request: dev -> main

### 1. Gate Failure State (Regression Triggered)
When `eval/run_eval.py` detects any gate failure:
- `recall@5` falls $> 5$ percentage points below baseline
- Any must-abstain question is answered from context (`answered_from_context: true`)
- Citation validity falls below $95\%$

The runner exits with code `1`, causing the `e2e-eval` GitHub Actions job to fail.

Under branch protection rules on `main`:
- **PR Merge Button State**: GREYED-OUT / DISABLED
- **Status Notice**: `Merging is blocked: Required status checks have not passed yet.`
- **Failing Job**: `e2e-eval / Golden evaluation gate (failure)`

### 2. Passing State (Remedy Verified)
Once the regression is corrected and tests re-run:
- `e2e-eval` exits with code `0`.
- All 6 checks turn green.
- The green **"Merge pull request"** button is unlocked.
