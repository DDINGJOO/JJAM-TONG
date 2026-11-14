# 로컬 메서드 근거 화면

PostgreSQL에 보관한 분석본을 브라우저에서 선택하고 메서드의 호출 후보와 저장된 실제 Trace를 확인한다. Trace는 요청 처리 중 기록한 실행 구간의 묶음이다. 대상 앱의 업무 소스는 가져오지 않으며 기존 `EvidenceReader`의 버전 대조·부분 수집 판정을 사용한다.

## 실행

Python 3.9 이상과 기존 Psycopg(PostgreSQL용 Python 드라이버) 환경을 사용한다. 새 패키지나 JavaScript 빌드 도구는 필요하지 않다. DB 준비 방법은 [저장 공통부](../evidence_store/README.md)를 따른다.

```sh
export JJAMTONG_EVIDENCE_DSN='postgresql://evidence:synthetic-local-only@127.0.0.1:29632/evidence'
.local/storage-lab/venv/bin/python -m tools.evidence_web --tenant "$TENANT"
```

`http://127.0.0.1:28740`을 연 뒤 분석본을 직접 선택한다. `--port`로 포트를 바꿀 수 있다. 서버는 로컬 루프백 주소에만 연결한다. DB 연결 문자열은 서버 환경 변수에서 읽으며 브라우저에 전달하지 않는다.

실행 기록을 함께 보려면 기존 OTel(OpenTelemetry) 로깅 파일과 당시 계측 설정의 SHA-256 해시를 지정한다. 선택한 Trace만 공개하려면 `--trace-id`도 지정한다.

```sh
.local/storage-lab/venv/bin/python -m tools.evidence_web \
  --tenant "$TENANT" --trace-log "$OTLP_LOG" \
  --telemetry-config "$TELEMETRY_CONFIG_SHA256" --trace-id "$TRACE_ID"
```

파일은 **서버가 시작할 때 한 번** 읽고 허용 항목만 메모리에 보관한다. 파일이 바뀌어도 자동으로 다시 읽지 않는다. Trace는 이 단계에서 DB에 저장하지 않는다. `Ctrl+C`로 서버를 종료하며 DB나 다른 컨테이너를 정리하지 않는다.

## 화면과 조회 계약

| 흐름 | 조회와 해석 |
| --- | --- |
| 분석본 선택 | 서버에 설정한 조직 라벨의 목록만 조회한다. run ID의 문자열 역순이며 생성 시간순이 아니다. 최신 빌드를 자동 선택하지 않는다. |
| 메서드 검색 | 선택한 분석본·분석기의 모듈·클래스·메서드·JVM descriptor를 검색한다. descriptor는 매개변수와 반환 타입을 포함한 식별자다. |
| 정적 그래프 | 나가는 호출 후보를 조회한다. 실제 실행을 뜻하지 않으며 JavaParser와 WALA를 합치지 않는다. |
| Trace 상세 | 선택한 분석 ID·해시의 빌드와 수집 기록을 대조한다. 다른 빌드면 `MISMATCH`로 표시하고 메서드를 연결하지 않는다. |
| 불확실성 | 부분 수집·미수집 부모·미해결 overload를 그대로 표시한다. 이름 후보가 하나여도 실행 시 descriptor를 직접 관측했다는 뜻은 아니다. |

목록·그래프·Trace의 기본 표시는 `BoardController.create`처럼 클래스명부터 시작한다. 전체 패키지·모듈·descriptor는 상세에서 확인하며 검색·메서드 식별에는 원래 값을 사용한다. 같은 짧은 클래스명이 겹치면 패키지를 덧붙여 구분한다. 그래프는 시작점 주변을 읽기 좋은 배율로 열고, `전체`·`시작점`·확대/축소·드래그로 탐색한다. 작은 배율에서는 메서드 이름을 줄여 표시한다.

`GET /api/context`, `/api/snapshots`, `/api/snapshot`, `/api/methods`, `/api/graph`, `/api/traces`, `/api/trace`를 제공한다. 분석본을 사용하는 요청에는 `run_id`와 `index_sha256`이 모두 필요하다. 조직 라벨·파일 경로·DB 주소를 요청에서 바꾸는 기능은 없다. 저장·분석 실행·대상 앱 변경 API도 제공하지 않는다.

기본 그래프 상한은 깊이 4·노드 80·호출 근거 200개이며 HTTP 최대값은 12·200·500이다. 원본 저장 계약의 최대값보다 화면 범위를 좁혔다. 목록은 페이지 단위로 읽고 DB 쿼리 예산을 재사용한다. HTTP 동시 처리 상한은 8개이며 초과 요청에는 503을 반환한다. JSON 응답 상한은 4 MiB다. 이는 자원 사용 제한이며 검증된 엔터프라이즈 수용량을 뜻하지 않는다.

## 검증과 범위

```sh
JJAMTONG_EVIDENCE_DSN="$JJAMTONG_EVIDENCE_DSN" \
  .local/storage-lab/venv/bin/python -m unittest tools.evidence_web.test_workspace -v
node --check tools/evidence_web/static/app.js
```

실제 PostgreSQL 시험은 DSN을 명시해야 실행한다. 브라우저 QA(Quality Assurance, 품질 검증)와 실제 Boot 근거의 연결은 [로컬 화면 검증](../../docs/experiments/LOCAL-EVIDENCE-WORKSPACE.md)에 기록한다. 저장된 자유 형식의 진단·출처 설명은 브라우저에 그대로 보내지 않고 정해진 설명과 원본 한계 항목 수만 전달한다. 시작·종료 시간이 없거나 역전된 실행 구간은 시간값을 제거하고 부분 결과로 표시한다.

조직 라벨은 조회 범위이며 사용자 인증·인가가 아니다. HTTP 서버는 개발용이며 운영 인터넷 공개·프록시 배포·기업용 접근 통제를 지원하지 않는다. 정적 분석본은 목록을 새로고침해 확인하고 Trace는 시작 파일의 고정 캡처를 사용한다. 지속 수집·실시간 화면 갱신·전체 MSA 타임라인과는 구분한다.
