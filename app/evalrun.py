"""Retrieval evaluation.

Each case checks that the expected passage appears in the top-3 search
results (or that an out-of-domain question is correctly refused).
Run after every tuning change — the score is also your honest sales
number (「初期精度◯%」).
"""

import json
from pathlib import Path

from .answer import COVERAGE_THRESHOLD, Engine


def run(path: Path, tenant: str = "demo") -> int:
    engine = Engine(tenant)
    cases = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    passed = 0
    for case in cases:
        question = case["question"]
        hits, coverage = engine.index.search(question, k=3)
        if case.get("expect_refusal"):
            ok = not hits or coverage < COVERAGE_THRESHOLD
            detail = f"coverage={coverage:.2f} (拒否しきい値 {COVERAGE_THRESHOLD})"
        else:
            expect = case["expect"]
            expect_doc = case.get("expect_doc", "")
            ok = any(
                expect in chunk["content"] and expect_doc in chunk["doc_title"]
                for chunk, _ in hits
            )
            top = f"{hits[0][0]['doc_title']}/{hits[0][0]['section']}" if hits else "なし"
            detail = f"top: {top}"
        passed += ok
        print(f"  {'✓' if ok else '✗'} {question}  [{detail}]")
    total = len(cases)
    pct = 100.0 * passed / total if total else 0.0
    print(f"\n結果: {passed}/{total} ({pct:.0f}%)")
    return 0 if passed == total else 1
