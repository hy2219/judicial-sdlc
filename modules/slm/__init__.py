"""Canned comparison response consumer; never performs model inference."""

from modules.transport import MockConnection, ServiceError


def compare_claim(connection: MockConnection, case_id: str, claim: str, source_text: str) -> dict:
    result = connection.post("/slm/compare", {
        "case_id": case_id, "claim": claim, "source_text": source_text,
    })
    if result.get("status") not in {"supported", "discrepancy", "insufficient_basis"}:
        raise ServiceError("알 수 없는 비교 상태입니다.")
    if not isinstance(result.get("reason"), str):
        raise ServiceError("비교 사유가 없습니다.")
    if result["status"] != "insufficient_basis":
        if result.get("claim_quote") != claim or result.get("source_quote") != source_text:
            raise ServiceError("응답의 인용문이 입력 원문과 다릅니다.")
    return result
