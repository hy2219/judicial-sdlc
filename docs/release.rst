설치파일 제작과 Artifact
=======================

기본 흐름
---------

Issue에서 Copilot을 Assign한 뒤 같은 PR에서 계획 확인과 구현을 진행합니다.
구현 완료 후 main에 squash 병합하면 소스 CI 뒤 ``Accepted PR to installer``가
검증·제작을 연결합니다. 사용자가 PR 번호·커밋 SHA를 입력하지 않습니다.
병합 전에는 Ready for review인 PR의 CI에서 전체 E2E를 실행합니다.
controller가 정확한 구현 head의 최신 test/e2e 성공·사람의 실제 squash 병합·변경 범위·계획 JSON을 확인하고
``Build merged workflow``를 호출합니다. 공통 modules/packaging/.github는
시나리오 작업에서 변경할 수 없습니다. 계획 승인 댓글의 의미는 자동 검증하지 않습니다.
PR E2E가 실패·미실행·skip·취소된 소스는 main Unit이 성공해도 제작하지 않습니다.
Linux PR E2E와 별개로 아래 Windows E2E를 유지해 글꼴·줄바꿈·GUI의 플랫폼 차이를 확인합니다.

운영 스크립트는 .github/scripts/에, 제작 스크립트는 packaging/에 있습니다.
제작 스크립트는 앱 기능이 아니며 결과 EXE를 실행하거나 설치하지 않습니다.

1. requirements와 의존성
-----------------------

Windows AMD64/Python 3.12 기준입니다. CPU 전용 PyTorch를 먼저 설치합니다::

    python -m pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cpu
    python -m pip install -r packaging/requirements.txt

packaging/requirements.txt → 루트 requirements.txt →
modules/ocr/requirements.txt → modules/ocr/requirements-text.txt 순으로 참조합니다.
검색·SLM mock은 표준 라이브러리만 쓰므로 별도의 빈 requirements를 만들지 않습니다.

2. 모델과 소스 시험
-------------------

::

    python .github/scripts/runtime_check.py --phase unit
    python modules/ocr/prepare.py
    python run.py --self-test
    python -m tests.ocr_check
    python .github/scripts/runtime_check.py --phase e2e

OCR 모델·고지는 빌드할 때 내려받고 해시를 확인합니다. weights/PDF/출력 파일은
Git에 넣지 않습니다. OCR 소스 시험은 합성 한국어·영어 스캔을 만들고 인식 중
네트워크 연결을 차단합니다. 앱이 OCR 모델을 실행 중 다운로드하지 않습니다.
Unit에서 통과한 앱 시험은 E2E에서 반복하지 않습니다. E2E는 시나리오의
RuntimeAcceptanceTests와 Unit에서 skip된 나머지 앱 시험을 전체 의존성으로 실행합니다.
같은 소스·시험 목록·실행 문맥의 Unit 기록이 필요하고 E2E에서 skip·expected-failure를 허용하지 않습니다.
시험이 없거나 실패하면 설치파일을 만들지 않습니다. 이는 실제 소스 흐름 검사이며
생성된 앱 EXE나 설치파일을 실행하는 단계가 아닙니다.

3. 앱 폴더와 Setup
------------------

::

    python packaging/freeze_windows.py
    python packaging/build_installer.py --version demo-1 --commit <실제-squash-SHA> --approval <병합검증기록.json>

기본 run.py와 app/에서 PyInstaller onedir payload를 만들고 Inno Setup으로
workflow-setup.exe를 만듭니다. tests/의 중립적인 시험 입력 생성기는 앱에 포함하지 않습니다.
PyInstaller --windowed를 사용해 앱 실행 시 별도 터미널 창을 표시하지 않습니다.
run.py가 GUI import 전에 표준 스트림 부재를 처리하고 시작 오류 hook을 설정합니다.
GUI 오류는 팝업과 문서 내용 없는 제한된 로컬 진단 로그로 알립니다.
모듈을 사용하는 코드는 Python import로 연결하고, 별도 EXE들을 호출하는 구조가 아닙니다.

PyTorch 2.8은 일반 초기화 경로에서도 ``torch.testing``을 사용하므로 테스트용이라는
이름만 보고 제외하면 안 됩니다. 기존 PyInstaller torch hook으로 함께 수집합니다.
``freeze_windows.py``는 완성된 ``workflow-app.exe``의 내장 Python 아카이브를 읽어
``torch.testing``과 하위 모듈·``torch.nn`` 등 지정된 OCR 필수 모듈의 바이트코드가
존재하고 해독 가능한지 확인합니다. 누락 시 실패하여 Setup 제작을 진행하지 않습니다.
개발 환경에서 import가 된다는 사실이나 ``_internal``의 소스 파일 존재만으로 통과시키지 않습니다.
이 검사는 EXE 실행이나 DLL 로딩 시험이 아니며 결과를 ``frozen-ocr-audit.json``에 남깁니다.

기관이 승인한 Windows 환경에서 사람이 포장된 앱의 짧은 가상 스캔 1쪽을 처리하여
PyTorch 초기화·모델 로딩·OCR 결과 표시까지 확인해야 실제 배포 동작을 확인할 수 있습니다.
창이 뜨거나 텍스트 PDF만 읽히는 것으로 OCR 패키징 성공을 판단하지 않습니다.
이 시작 오류의 재현에 53쪽 전체 처리나 실제 재판자료는 필요하지 않습니다.

설치 설계서 windows-installer.iss는 Program Files 제품 폴더, 설치 파일 목록,
바로가기와 제품 제거 기능을 정의합니다. Python DLL·CRAFT/KLOCR 모델은 설치 폴더의
_internal 아래에 놓입니다. 설치 후 앱은 workflow-app.exe입니다.
이는 단일 실행 EXE가 아니므로 설치된 앱 EXE만 떼어서 옮기면 안 됩니다.

KLOCR safetensors와 고정된 processor/config 파일, CRAFT 검출 모델을 함께 번들합니다.
설치파일의 KLOCR 가중치는 CC-BY-NC-SA-4.0 조건을 따릅니다. 원문 모델 카드와
라이선스를 보존하며, 상업 이용·기관 배포·재배포 권한은 사용자가 별도로 검토해야 합니다.
release-metadata.json schema 10에 엔진·리비전·신뢰도 의미·라이선스 검토 필요를 기록합니다.

설치에는 관리자 권한과 조직의 설치/실행 허가가 필요합니다. 코드서명은 미설정이며
WDAC 허용을 보장하지 않습니다. Setup 자체의 임시 작업 파일까지 없어지는 것은
아닙니다. 보안 정책·PATH·기존 Python/Tesseract를 변경하지 않고 앱도 자동 실행하지 않습니다.
사용자 문서는 선택한 별도 폴더에 보관하며 제거 프로그램이 삭제하지 않습니다.
작업·소스별 설치 ID가 달라 새 버전은 별도 설치되고 구버전을 자동 제거하지 않습니다.

4. 결과
-------

Artifact에는 설치파일, 메타데이터, 체크섬, 제3자 고지, payload 파일 목록,
installer 빌드 기록과 frozen-ocr-audit.json이 들어갑니다. 아카이브 검사 기록은
대상 workflow-app.exe의 해시를 포함하지만 실제 실행 성공을 뜻하지 않습니다.
보관 기간은 14일이며 원래 Issue에 링크를 게시합니다.
메타데이터에는 하나의 PR, 계획 blob SHA, 구현 head/실제 squash SHA,
사람 병합자와 변경 파일을 기록합니다. 계획 댓글 승인은 자동 검증하지 않았음을
명시하고 예전 두 PR/미병합 승인 기록은 거부합니다.
로컬 일반 PDF 처리, 콘솔 없는 빌드 설정과 진단 방식도 기록합니다.
이 기록은 실제 Windows 설치·실행 여부를 증명하지 않습니다.
입력 모델과 설치 컴파일러에 전달된 파일의 해시는 실행 검증이나 보안 인증이 아닙니다.
생성된 설치파일·앱은 실행하지 않으며 최종 바이너리 정적 분석 단계도 없습니다.
Release·이메일·자동 업데이트는 이 최소 템플릿의 범위에서 제외했습니다.

최신 템플릿의 새 복사본에서 같은 공통 workflow로 결과가 생성되는지 확인합니다.
공통 문제가 있으면 원본에서 고친 뒤 새 기준으로 다시 검토합니다.
샘플에서만 제작 스크립트를 고쳐 성공시키지 않습니다.
