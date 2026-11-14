# 근거의 식별자와 시간 모델 검증 결과

2026-11-14에 [#76](https://github.com/DDINGJOO/JJAM-TONG/issues/76)의 작은 계약 실험을 실행했다. **단위 시험 21개와 합성 시나리오 13개가 통과했다. 기존 PostgreSQL의 합성 분석 두 개를 원본 전체와 대조했고, 잘못된 버전 선택 16건을 거부했다.**

이 결과는 [논리 모델](../requirements/EVIDENCE-MODEL.md)과 [ADR 0012](../decisions/0012-evidence-identity-time-model.md)의 한정된 검증이다. 전체 플랫폼의 저장 엔진이나 물리 스키마를 확정한 결과가 아니다. 현재 `analysis`·`method`·`call` 테이블과 웹 조회 경로는 변경하지 않았다.

## 실행 범위와 판정

| 검증 | 입력과 판정 | 최종 결과 |
| --- | --- | --- |
| 새 단위 시험 | 식별 범위·관계 타입·시간·정정·조회 제한·메타데이터 연결과 회귀 반례 | 21개 통과 |
| 합성 계약 시나리오 | `BDD-MDL-001~013`에 대응하는 선택된 판정의 기대값과 실제 값 대조 | 13개 일치 |
| 실제 DB 읽기 | 지정한 이전·새 분석 원본 전체 JSON과 메타데이터 연결 대조 | 2개 일치 |
| 잘못된 선택 | 각 분석의 빌드 필드 5개, DB 원본 해시, 연결부 원본·설정 해시를 각각 변경 | 8개씩, 총 16개 거부 |
| 기존 계약 회귀 | 저장 계약·메서드 근거·웹 작업공간 시험 | 43개 중 40개 통과, 3개 건너뜀 |

기존 회귀 명령에서 건너뛴 3개는 별도 DB 접속 설정을 요구하는 웹·저장 통합 시험이다. 이번 명령에는 그 설정을 제공하지 않았다. 아래의 읽기 전용 검증은 실제 DB를 사용했지만, 이 세 시험 전체를 대체하지 않는다.

합성 시나리오는 [원시 결과](evidence-model-results.json)에 기대값과 실제 값 및 이유를 각각 기록한다. [BDD 명세](../../specs/features/13-evidence-model.feature) 전체를 Gherkin 실행기로 돌린 수락 테스트는 아니다.

| 시나리오 | 이번 실행에서 대조한 내용 |
| --- | --- |
| 001 | 같은 커밋·빌드 이름의 다른 산출물과 분석을 구분 |
| 002 | 서비스와 모듈의 다대다 관계 |
| 003 | 동시에 유효한 배포와 각 실행의 서로 다른 정확한 빌드 |
| 004 | 계정 범위·재생성 UID를 구분하고 동치 주장 뒤에도 원본 식별 보존 |
| 005 | 두 서비스의 공유 자원과 한 서비스의 복수 자원. 선언을 관측으로 반환하지 않음 |
| 006 | 유효 시점과 늦은 수집 시점 구분, 시간대 없는 입력 거부 |
| 007 | 정정 전후의 조회, 정정된 유효 구간과 철회 뒤 결과 |
| 008 | 주 빌드처럼 단일 값인 관계의 충돌과 두 출처 보존 |
| 009 | 잘못된 대상·관계·조직·불변 ID와 입력 변조 거부 |
| 010 | 정적 후보·선언·추론을 실제 관측으로 승격하지 않음 |
| 011 | 숨은 기록의 유무가 보이는 응답을 바꾸지 않음, 불완전 범위의 일반 응답 |
| 012 | 일반 결과·충돌 결과 모두 표시량 상한 적용, 잘못된 상한 거부 |
| 013 | 기존 분석의 다섯 빌드 필드·실행 ID·해시와 여섯 참조 종류만 연결 |

## 기존 PostgreSQL 분석과의 대조

DB 검증은 [이전 Java 통합 검증](JAVA-COMPACT-INTEGRATION.md)에서 보존한 합성 입력을 다시 읽었다. 분석마다 401,023줄인 이전·새 Java 빌드의 결과이며, **이번에 Java 분석이나 애플리케이션 요청을 새로 실행한 것은 아니다**.

| 항목 | 확인한 값 |
| --- | --- |
| 실행 환경 | Python 3.9.6, PostgreSQL 17.11 |
| 분석 선택 | 조직 `java-publication-73`, 실행 `scale-old`·`scale-new`, 각각의 정확한 `indexSha256` |
| 읽기 전용 | 연결마다 `REPEATABLE READ READ ONLY`를 설정. 서버의 `transaction_read_only=on` 확인 |
| 원본 대조 | DB에서 읽은 전체 JSON이 지정한 각 입력 파일의 전체 JSON과 일치 |
| 연결 범위 | Repository·SourceRevision·Module·ModuleBuild·Artifact·AnalysisSnapshot |
| 변경 작업 | 스키마 초기화·DB 발행·기존 분석 수정 없음 |

[DB 원시 결과](evidence-model-store-verification.json)는 입력 파일의 SHA-256, 정확한 빌드 필드·색인/설정 해시, 연결부 결과, 개별 거부 판정과 실험 소스 파일의 SHA-256을 포함한다. 파일 자체의 해시와 논리 JSON을 정규화한 색인 해시는 서로 다른 값이다. DB 접속 정보와 로컬 원본의 전체 경로는 기록하지 않는다.

## 검토에서 발견하고 고친 문제

구현 전에 구조 검토와 반례 검토를 순서대로 수행했다. 첫 구조 검토에서 요구한 관계의 다대다·정정 제약·조회 범위·메타데이터 연결 경계를 보완한 뒤 두 검토가 승인했다.

초기 구현 검토에서는 카탈로그 관계를 단일 값으로 처리한 문제, 저장소가 다른 소스·모듈 참조의 충돌, 정정·철회와 조회 제한의 빈틈을 발견했다. 관련 회귀 시험을 추가하고 계약과 구현을 맞췄다.

별도의 독립 코드 검토는 다음 두 항목을 지적했다. 두 회귀 시험이 수정 전에 실패함을 확인한 뒤 수정했으며, 재검에서는 지적 없이 승인됐다.

| 문제 | 수정과 판별 |
| --- | --- |
| 보이는 정정의 `supersedes`에 숨은 원 주장 ID가 포함됨 | 조회용 주장에서는 정정·철회 연결 ID를 일괄 생략. 숨은 이력이 없는 동등 주장과 객체·직렬화 결과가 같은지 확인. 원장은 원본 이력을 보존 |
| 시나리오 003의 기대 빌드 필드를 연결부 결과에서 가져옴 | 원본 입력을 독립 기대값으로 사용. 연결부 결과를 의도적으로 변조하면 해당 시나리오가 실패하는지 확인 |

만료한 정정이 원 주장을 되살리지 않는 시험도 정정만 만료하고 원 주장은 유효한 시점으로 보강했다. 한국어 문장·용어의 독립 AI 편집 검토에서는 시간 기준과 정정 대상의 표현을 고쳤다. 검토 지적·선택 이유·재검 결과는 [작업 이슈](https://github.com/DDINGJOO/JJAM-TONG/issues/76)에 남긴다.

## 실행 명령

표준 라이브러리만 사용하는 시험과 시나리오는 저장소 루트에서 실행한다.

```sh
python3 -m unittest experiments.evidence_model_lab.test_model -v
python3 -m experiments.evidence_model_lab.run \
  --output docs/experiments/evidence-model-results.json
```

DB 대조에는 기존 [저장 도구의 Psycopg 실행 환경](../../tools/evidence_store/README.md)과 정확한 분석 두 개가 필요하다. `JJAMTONG_EVIDENCE_DSN`은 기존 로컬 합성 DB의 접속 정보로 설정한다. 아래 상대 경로는 이번 실행에서 보존한 파일의 위치이며 저장소에 포함된 입력은 아니다. 다른 입력으로 실행하면 보고서의 해시와 판정도 해당 입력을 기준으로 생성된다.

```sh
.local/storage-lab/venv/bin/python -m experiments.evidence_model_lab.verify_store \
  --tenant java-publication-73 \
  --index .local/analysis-integration/actual-verified/index/scale-old.json \
          .local/analysis-integration/actual-verified/index/scale-new.json \
  --output docs/experiments/evidence-model-store-verification.json
```

기존 계약의 회귀 명령은 다음과 같다. 별도 접속 설정이 필요한 세 시험은 이 명령에서 건너뛰었다.

```sh
.local/storage-lab/venv/bin/python -m unittest \
  tools.evidence_store.test_contracts \
  tools.method_evidence.test_evidence \
  tools.evidence_web.test_workspace -v
```

## 다음 검증

이 실험은 메모리의 작은 관계 원장과 기존 분석의 메타데이터 연결까지 다룬다. 실제 인증·인가, 영구 ID 발급, 저장소 이관, 자동 발견, 다중 노드·지속 수용량, 실시간 수집, 클라우드·자산·보안 연동과 새 화면은 앞으로 구현하고 검증해야 한다. 이번 작업에서는 화면을 변경하거나 브라우저 QA를 수행하지 않았다.

상위 [#65](https://github.com/DDINGJOO/JJAM-TONG/issues/65)에서 빌드·모듈 명세와 변경 영향을 이 계약에 연결한다. HTTP·이벤트·배포·인프라·CMDB·SIEM도 [논리 모델의 후속 연결](../requirements/EVIDENCE-MODEL.md#검증과-남은-구현)에 포함되며 전체 구현 대상에서 제외하지 않는다.
