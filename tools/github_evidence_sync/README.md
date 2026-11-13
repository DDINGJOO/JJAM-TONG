# GitHub의 메서드 분석 결과를 로컬 DB에 저장한다

별도 [Playground](https://github.com/DDINGJOO/JJAM-TONG-playground)에 코드를 올리면 GitHub Actions가 해당 커밋의 `method-fixture`를 빌드·분석한다. 이 수집기는 성공한 실행의 분석 산출물(artifact)을 검증하고 기존 PostgreSQL 저장 어댑터로 가져온다. **Actions는 로컬 DB에 접속하지 않는다.** [설계 경계](../../docs/decisions/0006-github-method-evidence-pull.md)와 [실제 두 커밋의 검증 결과](../../docs/experiments/GITHUB-EVIDENCE-SYNC.md)를 함께 읽는다.

첫 경로는 Java 17 일반 JAR의 정적 호출 후보를 다룬다. MSA 게시판 전체의 Spring Boot 실행 JAR 분석이나 실제 trace의 지속 수집은 아직 연결하지 않았다. 결과에는 메서드 이름·관계와 버전 정보가 있으며 소스 본문과 JAR은 넣지 않는다.

## 로컬에서 가져온다

[저장 도구의 가상 환경·DB 초기화](../evidence_store/README.md#로컬에서-실행한다)를 먼저 수행한다. Python 3.9 이상과 기존 Psycopg 3.2.12를 재사용하며 새 의존성은 없다. 저장소 루트에서 실행한다.

```sh
export PYTHON=.local/evidence-store-venv/bin/python
export JJAMTONG_EVIDENCE_DSN='postgresql://evidence:synthetic-local-only@127.0.0.1:29632/evidence'
# 비밀 관리 도구나 셸의 비공개 환경에서 Actions 읽기 토큰을 설정한다.
# JJAMTONG_GITHUB_TOKEN 값을 파일이나 명령 인수에 기록하지 않는다.
"$PYTHON" -m tools.github_evidence_sync pull \
  --repository DDINGJOO/JJAM-TONG-playground --workflow ci.yml \
  --branch main --tenant local-team --run-id "$GITHUB_RUN_ID" \
  --receipts .local/github-sync/receipts
"$PYTHON" -m tools.github_evidence_sync watch \
  --repository DDINGJOO/JJAM-TONG-playground --workflow ci.yml \
  --branch main --tenant local-team --pages 3 --interval 30 \
  --receipts .local/github-sync/receipts
```

`JJAMTONG_GITHUB_TOKEN`과 `JJAMTONG_EVIDENCE_DSN`은 필수 환경 변수다. GitHub CLI의 현재 로그인 계정으로 자동 대체하지 않는다. GitHub 토큰에는 대상 저장소의 Actions 읽기 권한이 필요하다. 저장 도구는 `127.0.0.1:29632`에만 DB를 연결하며, 예제 DB 자격증명은 합성 로컬 전용이다. 토큰은 GitHub API 요청에만 보내고 artifact 다운로드의 다른 호스트에는 전달하지 않는다.

`pull --run-id`는 한 실행을 검증한다. `--run-id`를 빼면 설정한 workflow·브랜치의 성공한 실행을 페이지 범위 안에서 찾는다. `watch`는 같은 작업을 순차적으로 반복하며, 기본 간격은 한 확인을 마친 뒤 30초다. 최소 간격은 10초, 페이지 수는 이벤트 종류별로 기본 3·최대 10이다. 한 페이지에는 최대 100개 실행이 있다. `Ctrl+C`로 중단할 수 있으며 컴퓨터 재시작 후 자동 기동은 설정하지 않는다.

## 출처와 버전을 대조한다

수집기는 저장소 숫자 ID, workflow 경로, 브랜치, 실행 상태·이벤트·커밋·회차와 artifact의 출처를 대조한다. ZIP의 SHA-256이 GitHub가 제공한 digest와 같아야 한다. 내부에는 정확히 두 파일만 허용하며 manifest·색인 파일 해시·정규화한 색인 해시·빌드 식별자가 모두 일치해야 한다. 다운로드 뒤 실행과 artifact 정보를 다시 확인한 후 DB에 원자적으로 발행한다.

압축 다운로드는 12 MiB, 색인은 10 MiB, manifest는 16 KiB로 제한한다. 파일 추가·중복·경로 이동, 중복 JSON 키, 출처나 해시 불일치는 발행 전에 거부한다. 저장에 실패해도 이전 분석은 유지한다. 오류 메시지에는 토큰·다운로드 서명 URL·DB 접속 문자열을 출력하지 않는다.

## 정확한 분석을 조회한다

성공 시 JSON 영수증에 `analysis_run_id`·`index_sha256`·`revision`·`build`와 GitHub 실행·artifact 식별자를 출력한다. `--receipts`를 지정하면 DB 발행 성공 후 로컬 파일에도 저장한다. 영수증은 수집을 건너뛰는 신뢰 원장이 아니며, 파일을 지워도 같은 분석을 다시 가져올 수 있다. 같은 ID·해시는 `replay`가 되고 기존 DB 행은 바뀌지 않는다. DB 저장 뒤 영수증 기록이 실패해도 다음 수집에서 같은 분석을 재시도할 수 있다.

```sh
"$PYTHON" -m tools.evidence_store graph \
  --tenant local-team --run-id "$ANALYSIS_RUN_ID" --index-sha256 "$INDEX_SHA256" \
  --analyzer wala \
  --root method-fixture fixture.board.Service list '(Ljava/lang/String;)Ljava/lang/String;' \
  --depth 4 --nodes 200 --edges 500
```

`ANALYSIS_RUN_ID`와 `INDEX_SHA256`은 선택한 영수증의 분석 ID·색인 해시다. `GITHUB_RUN_ID`와 분석 ID는 다르다. 분석 ID는 `gh-저장소숫자ID-실행ID-회차` 형식이다. 이전·새 분석을 각각 지정해야 하며 최신 브랜치로 자동 대체하지 않는다. 정적 후보·미해결·부분 결과의 의미는 [저장·조회 계약](../evidence_store/README.md#그래프-결과를-읽는다)을 따른다.

## 중단과 보관 기한을 다룬다

현재 수집기는 매 확인마다 이미 저장한 artifact도 다시 검증하므로 반복 API 호출·다운로드 비용이 발생한다. 장애가 나면 다음 확인 때 재시도하지만 호출 제한에 따른 지수형 대기나 운영 작업 예산은 아직 없다. 페이지 범위 밖의 실행은 찾지 못할 수 있으며, 필요하면 `pull --run-id`로 지정한다. Playground의 분석 artifact 보관 기한은 7일이다. 그 안에 수집하지 못하고 만료·삭제된 결과는 DB에 자동 복원되지 않는다.

DB의 조직 라벨은 조회 조건이며 사용자 인증·인가를 대신하지 않는다. 신뢰할 수 있는 로컬 사용자를 위한 첫 도구다. 기업 권한·감사·장기 보존, 다중 작업자·자동 확장과 대형 프로젝트의 수용량은 앞으로 검증한다.

오프라인 경계 검증과 로컬 PostgreSQL 회귀 검증은 다음 명령으로 실행한다. PostgreSQL 검증은 위 환경 변수가 설정되어 있어야 실제 DB에 수행된다.

```sh
"$PYTHON" -m unittest tools.test_github_evidence_publish \
  tools.github_evidence_sync.test_collector tools.github_evidence_sync.test_integration_contract \
  tools.evidence_store.test_contracts \
  tools.evidence_store.test_postgres tools.method_evidence.test_evidence -v
```
