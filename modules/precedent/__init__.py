"""Demo session and lookup; no real credentials or court endpoints."""

from modules.transport import MockConnection, ServiceError


def login(connection: MockConnection) -> None:
    response = connection.post("/session", {"mode": "synthetic"})
    token = response.get("token")
    if not isinstance(token, str) or not 1 <= len(token) <= 200:
        raise ServiceError("모의 세션 응답이 잘못되었습니다.")
    connection.token = token


def search(connection: MockConnection, case_id: str) -> dict:
    result = connection.post("/precedents/search", {"case_id": case_id})
    status = result.get("status")
    if status not in {"found", "no_hit", "fixture_not_configured"}:
        raise ServiceError("알 수 없는 판례검색 상태입니다.")
    if status == "found":
        source = result.get("source")
        if (
            not isinstance(source, dict) or source.get("id") != case_id
            or source.get("authority") != "mock_fixture_only"
            or any(not isinstance(source.get(key), str) or not source[key]
                   for key in ("text", "title", "location"))
        ):
            raise ServiceError("모의 판례 원문의 식별정보가 잘못되었습니다.")
    elif result.get("source") is not None:
        raise ServiceError("조회 상태와 원문이 일치하지 않습니다.")
    return result
