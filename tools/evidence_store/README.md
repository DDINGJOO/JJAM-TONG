# 버전별 메서드 근거의 로컬 저장 공통부

분석 결과를 다시 조회할 때 다른 빌드의 메서드가 섞이면 잘못된 디버깅 근거가 된다. 이 도구는 기존 `method_evidence`가 만든 색인을 PostgreSQL에 보관하고, 선택한 분석의 정적 호출 후보와 실제 trace(요청 처리 중 기록한 호출 구간)를 각각 조회한다. 별도 대상 앱의 코드는 복사하지 않는다.

**첫 로컬 구현은 PostgreSQL 17.11과 기존 실험의 Psycopg 3.2.12를 재사용한다.** 저장 계약 `AnalysisRepository`와 그래프 조회 계약 `GraphQueryPort`를 나눴다. 계약은 소비자가 DB 제품을 몰라도 호출할 수 있는 Python 인터페이스다. 현재 PostgreSQL 어댑터가 둘을 구현하며, Neo4j 어댑터는 아직 없다. [선택 범위와 대안](../../docs/decisions/0005-local-versioned-evidence-store.md), [검증 결과](../../docs/experiments/VERSIONED-EVIDENCE-STORE.md)를 함께 읽는다.

## 로컬에서 실행한다

저장소 루트에서 Python 3.9 이상과 Docker Compose를 사용한다. 기존 가상 환경이 있으면 재사용한다. 의존성 목록은 기존 저장소 실험의 고정 버전이다.

```sh
python3 -m venv .local/evidence-store-venv
.local/evidence-store-venv/bin/pip install -r experiments/storage_lab/requirements.txt
export PYTHON=.local/evidence-store-venv/bin/python
docker compose -f tools/evidence_store/compose.yaml up -d --wait
export JJAMTONG_EVIDENCE_DSN='postgresql://evidence:synthetic-local-only@127.0.0.1:29632/evidence'
"$PYTHON" -m tools.evidence_store init
"$PYTHON" -m tools.evidence_store publish --tenant local-team --index "$INDEX_JSON"
"$PYTHON" -m tools.evidence_store graph \
  --tenant local-team --run-id "$ANALYSIS_RUN_ID" --index-sha256 "$INDEX_SHA256" \
  --analyzer wala --root "$MODULE" "$CLASS" "$METHOD" "$JVM_DESCRIPTOR" \
  --depth 4 --nodes 200 --edges 500
"$PYTHON" -m tools.evidence_store trace \
  --tenant local-team --run-id "$ANALYSIS_RUN_ID" --index-sha256 "$INDEX_SHA256" \
  --log "$OTLP_LOG" --trace-id "$TRACE_ID" --telemetry-config "$TELEMETRY_CONFIG_SHA256"
"$PYTHON" -m unittest tools.evidence_store.test_contracts tools.evidence_store.test_postgres \
  tools.method_evidence.test_evidence -v
docker compose -f tools/evidence_store/compose.yaml down
```

`INDEX_JSON`은 [기존 색인 생성 명령](../method_evidence/README.md)에서 받은 파일이다. `analysisRunId`와 `indexSha256`도 그 파일에서 가져온다. `--root`에는 모듈·클래스·이름·JVM descriptor 네 값을 모두 지정한다. descriptor는 인수·반환 타입을 포함한 메서드 식별자다. 이름은 같지만 인수 형식이 다른 메서드(overload)는 자동으로 선택하지 않는다. `-`로 시작하는 이름은 현재 CLI에서 지원하지 않는다.

Compose는 루프백 주소의 포트 29632에만 연결하며 CPU 1개·메모리 1 GiB로 제한한다. 예제 비밀번호는 합성 로컬 전용이다. `down`은 컨테이너·네트워크를 정리하고 데이터 볼륨을 보존한다. 기존 다른 Compose 프로젝트는 변경하지 않는다. DSN은 연결 정보를 담은 문자열이며 환경 변수로 읽는다. `tools.evidence_store` 하위 명령은 성공하면 JSON을 출력하고, 실패하면 종료 코드가 0이 아니다.

## 저장과 조회 계약

| 조건 | 실제 동작 |
| --- | --- |
| 새 조직 라벨·분석 실행 ID | 원본 색인과 분석기별 메서드·호출 관계를 같은 트랜잭션으로 발행 |
| 같은 ID·같은 색인 해시 재시도 | `created: false`; 기존 데이터를 그대로 반환 |
| 같은 ID·다른 색인 | `SnapshotConflict`; 덮어쓰지 않음 |
| 동시 발행 중 실패 | 원본과 그래프가 함께 롤백되어 일부 결과를 공개하지 않음 |
| 없는 이력 | `HISTORY_NOT_COLLECTED`; 최신 브랜치나 다른 빌드로 대체하지 않음 |
| 요청 해시와 원본·그래프 해시 불일치 | `VersionMismatch`; 결과를 연결하지 않음 |
| JavaParser / WALA 선택 | 각각의 메서드 목록·관계 종류·출처를 보존하고 두 관계를 합치지 않음 |
| 분석기 목록에 없는 호출 끝점 | 노드를 새로 만들지 않고 `danglingCalls`에 집계; 원본 호출은 색인에 보존 |
| 실제 trace | 기존 허용 항목 수집·빌드/설정 대조·미해결 overload 판정을 그대로 사용 |

트랜잭션은 원본과 조회용 관계를 전부 저장하거나 전부 취소하는 DB 작업 단위다. 원본 색인의 저장소·커밋·빌드·모듈·artifact 해시, 분석기·스키마·설정 버전을 보존한다. 분석 실행 ID가 같더라도 다른 조직 라벨의 데이터는 다른 행이다. **조직 라벨별 SQL 조건은 인증·인가가 아니다.** DB에 직접 연결할 수 있는 사용자를 신뢰하는 로컬 도구이며, 행 수준 접근 통제·기업 인증을 구현하지 않는다.

## 그래프 결과를 읽는다

선택한 분석기의 정확한 메서드에서 시작해 **나가는 호출 후보**를 단계별로 조회한다. 같은 메서드는 한 번 방문하므로 순환 호출도 종료한다. 결과의 `calls`는 탐색한 호출 지점의 근거이며, 도달한 모든 노드 사이의 관계나 모든 경로를 열거한 결과는 아니다. 마지막 깊이의 메서드에서 나가는 호출은 포함하지 않는다. 그 호출이 아직 방문하지 않은 메서드로 이어지면 `DEPTH_LIMIT`을 남긴다.

기본 상한은 깊이 4·메서드 200개·호출 근거 500개다. 최대 지정값은 12·5,000·10,000이다. 상한에 걸리면 `PARTIAL`과 `DEPTH_LIMIT`·`NODE_LIMIT`·`EDGE_LIMIT` 중 알려진 이유를 반환한다. 탐색 중 5초 예산과 DB 문장 시간 초과는 `PARTIAL`·`TIME_BUDGET`으로 반환한다. 시작 메서드를 확인하기 전에 시간 초과가 나면 `UNRESOLVED`·`TIME_BUDGET`으로 반환한다. 연결·락 대기와 취소 지연을 포함한 종단 응답 시간 5초를 보장하지 않는다.

분석기의 미해결·제외 항목과 목록 밖 호출은 분석 전체의 집계다. 이번 시작 메서드에서 그 항목에 도달했다는 뜻은 아니며, 해당 항목이 있으면 보수적으로 `PARTIAL`을 표시한다. 공백이 없는 합성 시험의 `STATIC_CANDIDATES`도 실제 실행이나 분석의 완전성을 입증하지 않는다. 원본 분석기의 한계가 그대로 남는다.

기존 파일 저장 도구는 같은 ID의 재시도를 거부한다. 이 DB 경로는 **동일 해시 재시도만 허용하는 별도 계약**이며 기존 파일 동작을 변경하지 않는다. 해시는 변경 탐지 수단이다. 호출자가 제공한 색인을 가져오며, 이 도구가 빌드 출처를 인증하거나 원격 JAR을 다시 검사하는 것은 아니다.

## 앞으로 검증할 항목

Neo4j를 연결할 때는 같은 분석 해시가 준비된 결과만 공개하는지 먼저 검증한다. 원본을 Neo4j로 옮기려면 저장 계약도 구현해야 한다. 현재 비동기 복제·재구축·outbox, 보존·삭제·마이그레이션, 인증·인가·감사, 고가용성·재해복구, 실제 대형 그래프의 지속 수용량은 구현하지 않았다. 자동 온보딩·배포·AWS/EKS/ECS/Kubernetes 지원 완료도 이번 산출물의 범위가 아니다.
