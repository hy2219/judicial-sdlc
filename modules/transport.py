"""Only a per-launch local mock is reachable; this is not a real API adapter."""

import json
from urllib import error, parse, request


class ServiceError(RuntimeError):
    pass


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class MockConnection:
    def __init__(self, base_url: str, bootstrap: str):
        url = parse.urlsplit(base_url)
        try:
            port = url.port
        except ValueError as exc:
            raise ValueError("Invalid mock port") from exc
        if (
            url.scheme != "http" or url.hostname != "127.0.0.1"
            or not port or url.username or url.password or url.path
            or url.query or url.fragment
        ):
            raise ValueError("Only an explicit loopback mock address is allowed")
        self.base_url = base_url
        self.bootstrap = bootstrap
        self.token = ""
        self.opener = request.build_opener(request.ProxyHandler({}), NoRedirect())

    def post(self, route: str, body: dict) -> dict:
        if route not in {"/session", "/precedents/search", "/slm/compare"}:
            raise ValueError("Unknown route")
        headers = {"Content-Type": "application/json", "X-Demo-Key": self.bootstrap}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = request.Request(
            self.base_url + route, data=json.dumps(body).encode("utf-8"),
            headers=headers, method="POST",
        )
        try:
            with self.opener.open(req, timeout=5) as response:
                raw = response.read(64_001)
        except error.HTTPError as exc:
            messages = {401: "모의 세션이 만료되었습니다.", 503: "모의 서비스가 응답 불가 상태입니다."}
            exc.close()
            raise ServiceError(messages.get(exc.code, f"모의 API 요청 실패: HTTP {exc.code}")) from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            raise ServiceError("모의 서버에 연결할 수 없습니다. 판례 미발견과 다른 오류입니다.") from exc
        if len(raw) > 64_000:
            raise ServiceError("모의 응답이 허용 크기를 초과했습니다.")
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise ServiceError("모의 응답 형식이 잘못되었습니다.") from exc
        if not isinstance(result, dict) or result.get("mock") is not True:
            raise ServiceError("모의 응답 표시가 없습니다. 처리를 중단합니다.")
        return result
