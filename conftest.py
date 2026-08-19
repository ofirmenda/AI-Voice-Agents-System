"""Collect pytest results and search Q/A logs into test_results.txt."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

REPORT_PATH = Path(__file__).parent / "test_results.txt"

_test_records: list[dict] = []
_search_entries: list[dict] = []


@pytest.fixture(scope="session")
def search_log():
    def log(question: str, result: dict, source: str = "") -> None:
        _search_entries.append(
            {
                "question": question,
                "score": result["score"],
                "text": result["text"],
                "source": source,
            }
        )

    return log


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" or (report.when == "setup" and report.outcome == "skipped"):
        _test_records.append(
            {
                "name": item.nodeid,
                "outcome": report.outcome,
                "duration": getattr(report, "duration", 0.0),
                "reason": str(report.longrepr) if report.outcome == "skipped" else "",
            }
        )


def _safe(text: str) -> str:
    return text.encode("ascii", errors="replace").decode("ascii")


def pytest_sessionfinish(session, exitstatus):
    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("TEST RESULTS")
    lines.append("=" * 80)
    lines.append(f"Timestamp:   {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Exit status: {exitstatus}")

    passed = sum(1 for r in _test_records if r["outcome"] == "passed")
    failed = sum(1 for r in _test_records if r["outcome"] == "failed")
    skipped = sum(1 for r in _test_records if r["outcome"] == "skipped")
    total = len(_test_records)
    total_duration = sum(r["duration"] for r in _test_records)

    lines.append("")
    lines.append(f"Total: {total}   Passed: {passed}   Failed: {failed}   Skipped: {skipped}")
    lines.append(f"Total duration: {total_duration:.2f}s")

    lines.append("")
    lines.append("-" * 80)
    lines.append("Per-test results")
    lines.append("-" * 80)
    label = {"passed": "PASS", "failed": "FAIL", "skipped": "SKIP"}
    for record in _test_records:
        mark = label.get(record["outcome"], "??")
        lines.append(f"  [{mark}] {record['duration']:6.2f}s  {record['name']}")
        if record["outcome"] == "skipped" and record["reason"]:
            reason = record["reason"].splitlines()[0][:120]
            lines.append(f"           reason: {reason}")

    if _search_entries:
        lines.append("")
        lines.append("=" * 80)
        lines.append("LIVE-API SEARCH LOG")
        lines.append("=" * 80)
        for entry in _search_entries:
            source = f"  [{entry['source']}]" if entry["source"] else ""
            lines.append("")
            lines.append(f"Q:{source} {entry['question']}")
            lines.append(f"Score: {entry['score']:.4f}")
            preview = _safe(entry["text"])[:600].replace("\n", " ")
            lines.append(f"Top chunk: {preview}...")
            lines.append("-" * 80)

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
