"""All text is invented workshop material, not a judgment or legal rule."""

CLAIMS = {
    "DEMO-001": "DEMO-001: The workshop door is open on Monday.",
    "DEMO-002": "DEMO-002: The workshop door is open every day.",
    "DEMO-003": "DEMO-003: The workshop provides free notebooks.",
}
SOURCE_TEXT = {
    "DEMO-001": "In this fictional workshop, the door is open on Monday.",
    "DEMO-002": "In this fictional workshop, the door is open only on Friday.",
}


def lookup(case_id: str) -> dict:
    if case_id == "DEMO-003":
        return {"status": "no_hit", "source": None}
    if case_id not in SOURCE_TEXT:
        return {"status": "fixture_not_configured", "source": None}
    return {
        "status": "found",
        "source": {
            "id": case_id,
            "title": f"Fictional workshop record {case_id}",
            "text": SOURCE_TEXT[case_id],
            "location": "synthetic record / paragraph 1",
            "authority": "mock_fixture_only",
        },
    }


def compare(case_id: str, claim: str, source_text: str) -> dict:
    if (
        case_id not in SOURCE_TEXT
        or claim != CLAIMS.get(case_id)
        or source_text != SOURCE_TEXT.get(case_id)
    ):
        return {"status": "insufficient_basis", "reason": "No matching comparison fixture."}
    return {
        "status": "supported" if case_id == "DEMO-001" else "discrepancy",
        "reason": "Prepared response, not model inference.",
        "claim_quote": claim,
        "source_quote": source_text,
    }
