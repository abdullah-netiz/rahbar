"""Retriever with full grounding material from FAST-NUCES policies.

Serves the full grounding corpus offline and in local testing, mapping questions
to real grounded passages covering academic warning, attendance, course load,
repeats, duration, tuition fees, and honest abstention on absent topics.
Switch to RETRIEVER=chroma in production when using the live Chroma StatefulSet.
"""

from __future__ import annotations

import re
from typing import Any

from ..schemas import Passage

# Real grounding material from FAST-NUCES corpus and fixture policies
_GROUNDING_CORPUS = [
    {
        "chunk_id": "fast-001",
        "keywords": ["attendance", "attend", "lecture", "lectures", "exam", "fa grade", "absent", "miss"],
        "text": "Attendance Regulations (Clause 1.21): A student must attend at least 80 percent of the scheduled lectures and lab sessions of each course to be eligible to sit for the final examination. A student who falls below the minimum attendance requirement receives the grade FA (Failure due to Attendance) in that course. The Head of Department may condone absence only for documented medical reasons.",
        "source": "Academic_Rules_Handbook_2026.pdf",
        "section": "1.21 Attendance",
        "page": 4,
        "score": 0.94,
    },
    {
        "chunk_id": "fast-002",
        "keywords": ["warning", "academic warning", "cgpa", "probation", "drop", "dropped", "2.00", "gpa"],
        "text": "Academic Warning (Clause 5.4): An undergraduate student whose cumulative grade point average (CGPA) falls below 2.00 at the end of a regular semester is placed on academic warning. A student who remains on academic warning for three consecutive regular semesters is dropped from the university degree programme.",
        "source": "Academic_Rules_Handbook_2026.pdf",
        "section": "5.4 Academic Warning",
        "page": 18,
        "score": 0.96,
    },
    {
        "chunk_id": "fast-003",
        "keywords": ["withdraw", "withdrawal", "drop course", "grade w", "10th week", "withdrawing"],
        "text": "Course Withdrawal (Clause 3.5): An undergraduate student may apply for course withdrawal before the end of the 10th week of classes during a regular semester. A grade of 'W' is assigned on the official transcript, which carries no grade points and does not affect the calculation of semester GPA or CGPA.",
        "source": "Academic_Rules_Handbook_2026.pdf",
        "section": "3.5 Course Withdrawal",
        "page": 12,
        "score": 0.93,
    },
    {
        "chunk_id": "fast-004",
        "keywords": ["repeat", "repeating", "improve", "grade replacement", "capped", "grade of c", "repeats"],
        "text": "Course Repeats (Clause 3.2): An undergraduate student may repeat any course in which a grade of C- or lower was earned to improve their CGPA. In accordance with the 2026 revised regulations, only the grade obtained in the most recent attempt counts toward cumulative GPA calculation, replacing earlier attempts.",
        "source": "Academic_Rules_Handbook_2026.pdf",
        "section": "3.2 Course Repeats",
        "page": 10,
        "score": 0.92,
    },
    {
        "chunk_id": "fast-005",
        "keywords": ["course load", "credit hour", "credit hours", "overload", "maximum load", "18 to 21", "load"],
        "text": "Course Load (Clause 2.2): The normal undergraduate course load for a regular semester is 15 to 18 credit hours. A student with a CGPA of 3.00 or higher may be permitted to register for an overload of up to 21 credit hours with prior written approval from the Head of Department.",
        "source": "Academic_Rules_Handbook_2026.pdf",
        "section": "2.2 Course Load",
        "page": 6,
        "score": 0.91,
    },
    {
        "chunk_id": "fast-006",
        "keywords": ["duration", "maximum duration", "degree duration", "7 years", "four-year", "years to complete"],
        "text": "Degree Duration (Clause 2.1): The normal duration of a four-year Bachelor of Science (BS) degree programme is 8 regular semesters. The maximum permissible duration to complete all degree requirements is 7 academic years from the date of admission.",
        "source": "Academic_Rules_Handbook_2026.pdf",
        "section": "2.1 Maximum Duration",
        "page": 5,
        "score": 0.90,
    },
    {
        "chunk_id": "fast-007",
        "keywords": ["dean", "deans list", "honour list", "honours", "medal", "medals", "3.50", "merit"],
        "text": "Honours and Medals (Clause 6.2): An undergraduate student who earns a semester GPA of 3.50 or higher with a normal course load of at least 15 credit hours and no failing or incomplete grades qualifies for placement on the Dean's Honour List.",
        "source": "Academic_Rules_Handbook_2026.pdf",
        "section": "6.2 Honours and Medals",
        "page": 22,
        "score": 0.95,
    },
    {
        "chunk_id": "fast-008",
        "keywords": ["recheck", "re-checking", "paper rechecking", "7 days", "answer script", "paper checking", "script"],
        "text": "Re-checking of Examination Papers (Clause 4.8): A student may formally apply for re-checking of an examination answer script within 7 days of the declaration of official results by submitting the prescribed fee to the Controller of Examinations. Re-checking is strictly limited to arithmetic totaling errors and unmarked questions.",
        "source": "Academic_Rules_Handbook_2026.pdf",
        "section": "4.8 Re-checking of Papers",
        "page": 16,
        "score": 0.92,
    },
    {
        "chunk_id": "fast-009",
        "keywords": ["ai", "generative ai", "chatgpt", "plagiarism", "dishonesty", "copilot", "unauthorized use", "claude"],
        "text": "Generative AI Policy: Unauthorized use of Generative AI tools (including ChatGPT, GitHub Copilot, and Claude) in academic coursework, assignments, or examinations without explicit written permission from the course instructor constitutes academic dishonesty and plagiarism under university disciplinary rules.",
        "source": "Student_Handbook_2026.pdf",
        "section": "Generative AI Policy",
        "page": 42,
        "score": 0.94,
    },
    {
        "chunk_id": "fast-010",
        "keywords": ["tuition", "fee", "fees", "credit hour", "10,000", "bs fee", "admission fee", "cost", "per credit"],
        "text": "Tuition Fees (Fee Structure 2026-27): Tuition fee for undergraduate BS programmes (all disciplines including CS, SE, EE, and BBA) is PKR 10,000 per credit hour. Graduate MS programmes tuition fee is PKR 12,500 per credit hour. Admission fee is PKR 25,000 (one-time non-refundable).",
        "source": "Fee Structure page",
        "section": "1. Tuition",
        "page": 1,
        "score": 0.95,
    },
    {
        "chunk_id": "fast-011",
        "keywords": ["refund", "refunds", "late registration", "transcript fee", "campus transfer", "charges"],
        "text": "Other University Charges & Refund Policy: Late registration surcharge is PKR 3,000. Official transcript fee is PKR 1,500 per copy. Campus transfer fee is PKR 5,000. Tuition fee is refunded 100% when a course is dropped within the first 10 days of classes, 50% between days 11 and 20, and 0% after day 20.",
        "source": "Fee Structure page",
        "section": "2. Other Charges and Refunds",
        "page": 2,
        "score": 0.93,
    },
    {
        "chunk_id": "fast-012",
        "keywords": ["prerequisite", "prerequisites", "advanced course", "concurrent registration", "prereq"],
        "text": "Prerequisite Requirements (Clause 2.4): A student must earn a passing grade in all prerequisite courses prior to enrolling in advanced courses. Concurrent registration in a course and its prerequisite is strictly prohibited under university regulations.",
        "source": "Academic_Rules_Handbook_2026.pdf",
        "section": "2.4 Prerequisites",
        "page": 7,
        "score": 0.91,
    },
    {
        "chunk_id": "fast-013",
        "keywords": ["2023", "old", "older", "superseded", "previous", "1.75", "75%"],
        "text": "Undergraduate Academic Rules (2023 Edition - Superseded): Under the August 2023 rules, academic warning was issued when CGPA fell below 1.75, two consecutive warnings resulted in programme dismissal, and attendance requirement was 75%.",
        "source": "Undergraduate-Academic-Rules-Aug-2023.pdf",
        "section": "2. Academic Warning (2023)",
        "page": 14,
        "score": 0.88,
    },
]

# Baseline passages for starter tests and fallback
_DEFAULT_PASSAGES = [
    Passage(
        chunk_id="fast-001",
        text=_GROUNDING_CORPUS[0]["text"],
        source=_GROUNDING_CORPUS[0]["source"],
        section=_GROUNDING_CORPUS[0]["section"],
        page=_GROUNDING_CORPUS[0]["page"],
        score=_GROUNDING_CORPUS[0]["score"],
    ),
    Passage(
        chunk_id="fast-002",
        text=_GROUNDING_CORPUS[1]["text"],
        source=_GROUNDING_CORPUS[1]["source"],
        section=_GROUNDING_CORPUS[1]["section"],
        page=_GROUNDING_CORPUS[1]["page"],
        score=_GROUNDING_CORPUS[1]["score"],
    ),
    Passage(
        chunk_id="fast-010",
        text=_GROUNDING_CORPUS[9]["text"],
        source=_GROUNDING_CORPUS[9]["source"],
        section=_GROUNDING_CORPUS[9]["section"],
        page=_GROUNDING_CORPUS[9]["page"],
        score=_GROUNDING_CORPUS[9]["score"],
    ),
]


class StubRetriever:
    name = "stub"

    def retrieve(self, question: str, k: int) -> list[Passage]:
        q_lower = question.lower()

        # Deliberately absent topics (hostel, accommodation, mess, bus transport) -> trigger honest abstention
        absent_topics = ["hostel", "hostels", "dorm", "dormitory", "mess", "transport bus", "bus route", "accommodation"]
        if any(re.search(rf"\b{re.escape(w)}\b", q_lower) for w in absent_topics):
            return []

        # Find matching passages from the grounding corpus based on keyword hits
        scored_matches: list[tuple[int, dict[str, Any]]] = []
        for entry in _GROUNDING_CORPUS:
            hits = 0
            for kw in entry["keywords"]:
                if kw in q_lower:
                    hits += 2 if " " in kw else 1
            if hits > 0:
                scored_matches.append((hits, entry))

        if scored_matches:
            scored_matches.sort(key=lambda x: x[0], reverse=True)
            results: list[Passage] = []
            for _, entry in scored_matches[:k]:
                results.append(
                    Passage(
                        chunk_id=entry["chunk_id"],
                        text=entry["text"],
                        source=entry["source"],
                        section=entry["section"],
                        page=entry["page"],
                        score=entry["score"],
                    )
                )
            # Ensure at least min(k, 3) passages returned if available
            if len(results) < k:
                for def_p in _DEFAULT_PASSAGES:
                    if def_p.chunk_id not in {r.chunk_id for r in results}:
                        results.append(def_p.model_copy())
                    if len(results) >= k:
                        break
            return results[:k]

        # Fallback for starter unit tests or general test questions
        return [p.model_copy() for p in _DEFAULT_PASSAGES[:k]]
