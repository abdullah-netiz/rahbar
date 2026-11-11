"""Unit tests for the evaluation runner metrics and gates (section 5).

Verifies recall@k, citation validity, abstention correctness, and gate failures.
Runs offline without network calls.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add eval to sys.path
EVAL_DIR = Path(__file__).resolve().parent.parent.parent / "eval"
sys.path.insert(0, str(EVAL_DIR))

from run_eval import citation_validity, gate, recall_at_k  # noqa: E402


def test_recall_at_k_calculation() -> None:
    relevant = [
        {"source": "handbook-2026.pdf", "section": "1.21 Attendance"},
        {"source": "handbook-2026.pdf", "section": "5.4 Warning"},
    ]
    retrieved = [
        {"source": "handbook-2026.pdf", "section": "1.21 Attendance"},
        {"source": "other.pdf", "section": "Intro"},
        {"source": "handbook-2026.pdf", "section": "5.4 Warning"},
    ]

    # At k=1, only 1 of 2 relevant retrieved -> 0.5
    assert recall_at_k(relevant, retrieved, 1) == 0.5
    # At k=3, both relevant passages retrieved -> 1.0
    assert recall_at_k(relevant, retrieved, 3) == 1.0


def test_recall_at_k_returns_none_for_must_abstain() -> None:
    # Must-abstain questions have empty relevant passages
    assert recall_at_k([], [{"source": "any.pdf", "section": "1"}], 5) is None


def test_citation_validity_calculation() -> None:
    response_valid = {
        "citations": [{"source": "handbook.pdf", "section": "1.21"}],
        "retrieved": [{"source": "handbook.pdf", "section": "1.21"}],
    }
    assert citation_validity(response_valid) == 1.0

    response_fabricated = {
        "citations": [
            {"source": "handbook.pdf", "section": "1.21"},
            {"source": "ghost.pdf", "section": "Fake"},
        ],
        "retrieved": [{"source": "handbook.pdf", "section": "1.21"}],
    }
    assert citation_validity(response_fabricated) == 0.5


def test_gate_detects_recall_regression_and_hallucination() -> None:
    baseline = {
        "recall@5": 0.85,
        "citation_validity": 0.98,
        "abstention_correctness": 1.0,
    }

    # Regression: recall dropped by > 0.05
    results_regressed = {
        "recall@5": 0.78,
        "citation_validity": 0.98,
        "abstention_correctness": 1.0,
    }
    failures = gate(results_regressed, baseline)
    assert len(failures) == 1
    assert "recall@5 dropped" in failures[0]

    # Failure: failed to abstain on must-abstain question
    results_answered_out_of_scope = {
        "recall@5": 0.85,
        "citation_validity": 0.98,
        "abstention_correctness": 0.90,  # Must be 1.0
    }
    failures_abst = gate(results_answered_out_of_scope, baseline)
    assert any("abstention correctness" in f for f in failures_abst)
