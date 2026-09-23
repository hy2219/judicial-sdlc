빌딩 블록 호출 방법
==================

실행되는 코드는 modules/, 작업마다 바꾸는 코드는 app/에 둡니다.
Skill은 Copilot이 코드를 작성할 때 참고하는 안내서이지 실행 모듈이 아닙니다.
Python 자체는 런타임입니다. 별도의 python 모듈이나 플러그인 엔진은 필요 없습니다.

OCR: 파일 → 페이지별 글자
-------------------------

:위치: modules/ocr/
:함수: read_document(path: Path, *, synthetic_only: bool = False) -> list[PageText]
:의존성: modules/ocr/requirements.txt

PageText에는 page, text, method, blocks, image_size, warnings가 있습니다.
method는 pdf_text 또는 klocr이며 좌표가 있는 경우 렌더링 페이지의 픽셀 단위입니다.
인쇄 쪽수·줄번호와 혼동하지 마세요. DocumentError/OCRUnavailable은 화면에 표시하고
빈 결과로 바꾸지 않습니다.
기본값은 합성 표시 없는 일반 PDF도 로컬로 읽습니다. 최대 50MB·100쪽이며
암호화·주석/양식·과도한 렌더링 크기는 거부합니다. 합성 입력 생성은 필수 절차가 아닙니다.
실제 PDF는 GitHub/Agent/CI로 보내지 않고 사용자 PC에서만 확인합니다.
OCR 이미지 페이지는 2.5배 렌더링 전 3,200,000픽셀·한 변 2200픽셀 상한을 확인합니다.
A4 595×842pt는 1488×2105픽셀로 범위 안이며 840×1080pt는 거부합니다.
직접 recognize(image)를 호출해도 같은 이미지 상한이 적용됩니다.
한도 초과는 해당 쪽의 DocumentError로 중단하며 앞쪽의 일부 결과를 성공으로 반환하지 않습니다.
입력을 자동으로 자르거나 페이지를 건너뛰지 않고 원본은 변경하지 않습니다.

::

    from pathlib import Path
    from modules.ocr import read_document

    pages = read_document(Path("local/synthetic.pdf"))
    for page in pages:
        print(page.page, page.method, page.text, page.warnings)

중립적인 OCR 시험 입력은 ``python -m tests.ocr_fixtures --text local/synthetic.pdf``
로 생성합니다. 스캔 생성은 --scan입니다. 모델은 개발/빌드 시
``python modules/ocr/prepare.py``로 준비하고 런타임 다운로드는 금지합니다.
합성 표시를 반드시 확인하는 개발 시험에서만 synthetic_only=True를 지정합니다.

CRAFT가 검출한 영역을 KLOCR이 CPU로 인식합니다. EasyOCR는 검출에만 사용합니다.
CRAFT는 canvas_size=1536, mag_ratio=1.0으로 검출 연산의 크기를 제한합니다.
EasyOCR가 원래 이미지 좌표로 되돌린 영역을 원래 해상도에서 잘라 KLOCR에 전달합니다.
렌더링 이미지·PageText.image_size·원문 대조 좌표를 검출용 축소 이미지로 바꾸지 않습니다.
입력/검출 크기 제한은 RAM 사용량의 보장값이 아니며 실제 시연 PC에서 정확도·자원을 확인해야 합니다.
words에는 원문 box, confidence, confidence_kind, warnings가 남습니다.
confidence는 비보정 토큰 확률의 기하평균이며 OCR 정확도 인증값이 아닙니다.
빈 인식과 토큰 길이 제한 경고도 보존합니다. 모델·설정·토크나이저는
고정 SHA-256을 확인한 assets/klocr 안의 파일만 읽으며 실행 중에는 다운로드하지 않습니다.
가중치 CC-BY-NC-SA-4.0 조건과 기관 배포 권한은 별도 확인해야 합니다.

판례검색: 식별자 → 가상 기록
-----------------------------

:위치: modules/precedent/
:함수: login(connection) -> None, search(connection, case_id) -> dict
:의존성: Python 표준 라이브러리만 사용, 별도 requirements 없음

login은 실제 계정을 받지 않고 모의 세션을 만듭니다.
search 결과는 found / no_hit / fixture_not_configured입니다.
found에는 source.id/title/text/location/authority가 있습니다.
접속 실패·세션 만료는 ServiceError이며 no_hit으로 바꾸지 않습니다.

::

    from mock_server.server import running_server
    from modules.transport import MockConnection
    from modules.precedent import login, search

    with running_server() as (url, key, events):
        connection = MockConnection(url, key)
        login(connection)
        found = search(connection, "DEMO-001")

이 서버는 같은 PC의 loopback에서만 작업 중 실행됩니다.
실제 법원 API로 전환하려면 별도의 승인된 인증·스키마 구현이 필요합니다.
주소만 바꿔 사용할 수 있도록 만든 범용 외부 클라이언트가 아닙니다.

시나리오별 가상 원문 주입
~~~~~~~~~~~~~~~~~~~~~~~~

``running_server(sources=...)``에 복사본의 ``app/``에서 작성한 가상 기록을
전달할 수 있습니다. 공통 서버나 기존 fixture를 고치지 않아도 실제 loopback HTTP로
조회됩니다. 아래 식별자는 중립 예시이며 판례 시나리오의 번호·본문은 복사본에서
요구사항에 맞춰 작성합니다. 로그인·주소·요청·응답은 실제 기관 명세를 확인하지 못해
임의로 만든 계약입니다.

::

    sources = {
        "SYNTHETIC-A": {
            "title": "Fictional workshop record",
            "text": "The fictional workshop door is blue.",
            "location": "Synthetic record / paragraph 1",
        },
        "SYNTHETIC-B": None,
    }
    with running_server(sources=sources) as (url, key, events):
        connection = MockConnection(url, key)
        login(connection)
        found = search(connection, "SYNTHETIC-A")

Python ``dict``의 각 값은 title/text/location의 비어 있지 않은 문자열 3개,
또는 명시적인 모의 검색 결과 없음을 뜻하는 ``None``입니다.
``id``와 ``authority=mock_fixture_only``는 서버가 부여합니다.
미등록 키는 ``fixture_not_configured``, ``None``으로 등록된 키는 ``no_hit``이며
어느 쪽도 실제 판결의 부존재를 뜻하지 않습니다. 빈 dict는 모두 미등록 상태입니다.
응답 크기가 클라이언트 상한을 넘는 자료는 서버 시작 전에 거부합니다.
시작 후 호출 측 dict를 바꾸어도 응답은 달라지지 않고 다른 서버와도 섞이지 않습니다.

사용자에게는 가상 원문·출처와 입력의 인용문을 나란히 보여주고 모의임을 표시합니다.
이 API는 합성 데이터 용도이며 실자료를 fixture로 만들거나 실제 로그인 정보를 넣지 않습니다.
기본 앱은 자동 호출하지 않습니다. 시나리오의 모의 조회는 기본 꺼짐으로 두고
독립 가상 입력임을 확인한 시연 경로에서만 활성화합니다. 일반 로컬 PDF 읽기는 유지합니다.
``sources``를 전달한 세션의 SLM 비교는 ``insufficient_basis``를 반환합니다.
맞춤 검색 원문을 넣는다고 의미 비교나 RAG가 구현되는 것은 아닙니다.
기존 ``sources`` 없는 중립 DEMO 비교 예시는 그대로 유지됩니다.

SLM: 인용문과 원문 → 고정 비교 응답
-----------------------------------

:위치: modules/slm/
:함수: compare_claim(connection, case_id, claim, source_text) -> dict
:의존성: Python 표준 라이브러리만 사용, 별도 requirements 없음

현재 모의 부품은 비교용 계약입니다. 일반 질문·임의 RAG 검색은 구현하지 않았습니다.
준비된 합성 입력이면 supported 또는 discrepancy, 등록하지 않은 문구이면
insufficient_basis를 반환합니다. 실제 생성형 AI 추론이나 판례 검증이 아닙니다.

::

    from modules.slm import compare_claim

    if found["status"] == "found":
        comparison = compare_claim(
            connection,
            "DEMO-001",
            "DEMO-001: The workshop door is open on Monday.",
            found["source"]["text"],
        )

위 코드는 앞의 running_server 블록 안에 넣습니다. 원문이 없으면 비교를 건너뛰고
‘확인 불가’로 표시합니다. 조회·비교 중 무엇이 실패했는지 숨기지 않습니다.

커스텀 로직과 오케스트레이션
----------------------------

``app/pipeline.py``의 run_pipeline은 화면이 호출하는 함수입니다.
기본 구현은 transform_pages를 거쳐 페이지를 JSON으로 보여줄 뿐 검색·SLM을
자동으로 사용하지 않습니다. 일반 Python 함수로 중간 작업을 추가합니다.

::

    def select_pages(pages, keyword):
        return [page for page in pages if keyword in page.text]

    def transform_pages(pages):
        return select_pages(pages, "교육")

더 복잡한 흐름에서는 run_pipeline에서 OCR 결과 → 맞춤 추출 함수 →
검색 → 맞춤 조건 분기 → 비교 → 출력용 dict를 연결합니다.
완성된 시나리오는 템플릿에 없습니다. 복제한 시나리오 저장소에서 승인된 요구사항에
따라 추출·계산·조합·화면 코드를 app/에 새로 작성합니다.
공통 modules/는 그대로 재사용하고 업무별 로직을 공통 부품에 끼워 넣지 않습니다.

계약은 작게 유지합니다. GUI는 run_pipeline의 JSON 직렬화 가능한 dict를 표시하고,
실패는 예외로 받아 이전 결과를 지웁니다. 표·체크박스 같은 화면은 app/gui.py에서
업무에 맞게 추가합니다. 입력·출력 형식이나 기능을 바꾸면 tests/test_app.py에
그 요청의 합성 정답과 실패 사례를 함께 작성합니다.

요구사항 파일
-------------

루트 requirements.txt는 모듈별 런타임 요구사항을 참조하는 진입점입니다.
가벼운 text-PDF 시험만 할 때는 modules/ocr/requirements-text.txt,
실제 OCR 포함 실행은 requirements.txt, 제작은 packaging/requirements.txt를 씁니다.
모듈마다 별도 설치하면 버전 충돌이 감춰질 수 있으므로 실제 배포는 통합 설치로 확인합니다.
