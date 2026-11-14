# Versioned evidence model lab

파이썬 표준 라이브러리로 저장소·빌드·분석본의 정확한 식별과 시간별 관계 주장을 검증하는 작은 실험이다. 관계 주장(claim)은 출처가 특정 관계를 뒷받침한다는 기록이다. 제품용 그래프 저장소와 자동 발견은 별도 구현 대상이다.

`EntityRef`는 대상 참조다. 대상 종류, 조직(`tenant`), 공급원 범위(`provider`), 원본 식별자(`native_id`), 재생성 구분값(`incarnation`)으로 동일성을 정한다. 표시 이름으로 합치지 않는다. 공급원 간 동치는 `EQUIVALENT_TO` 주장으로 표현하며 두 참조를 보존한다.

Pod와 컨테이너·프로세스 런타임을 구분하므로 하나의 Pod에 여러 런타임·빌드를 연결할 수 있다. `RUNTIME_PRIMARY_BUILD`는 런타임의 주 빌드만 단일 값으로 검사한다. 추가 로드 빌드는 복수 값 `RUNTIME_USES_BUILD`로 남긴다. 서비스와 모듈의 `SERVICE_USES_MODULE`, 카탈로그와 자원의 `CATALOG_MAPS`도 복수 값을 허용한다.

`ClaimLog`는 원본을 덮어쓰지 않고 추가 기록만 허용하는 원장이다. `validFrom`·`validTo`는 시작을 포함하고 끝을 제외하는 UTC 유효 구간이다. `knownAt`은 플랫폼이 그 주장을 알게 된 시각이다. 끝이 없는 유효 구간도 현재 상태의 증명은 아니다.

정정·철회는 같은 조직·출처 흐름·주어·관계·근거 종류의 이미 알려진 주장만 가리킨다. 출처 흐름은 `tenant + provider + native_id`로 구분한다. 정정의 원본 기록 참조(`original_ref`)는 바뀔 수 있다. 철회는 원 주장과 같은 목적어를 가져야 하며 활성 주장으로 반환되지 않는다. 알려진 정정·철회는 유효 구간 검사 전에 원 주장을 제외하므로 만료한 정정이 이전 주장을 되살리지 않는다.

`import_v1(index, tenant, provider=...)`는 입력 JSON을 먼저 복사하고 기존의 엄격한 `prepare(index)` 검사를 적용한다. 연결 결과인 `V1Bridge`는 다섯 `BuildIdentity` 필드와 분석 실행 ID·색인 해시·설정 해시를 그대로 보존한다. SourceRevision은 저장소와 소스 버전, Module은 저장소와 모듈, ModuleBuild는 다섯 빌드 필드 전체를 정규화한 JSON의 SHA-256으로 구분한다. 긴 JSON을 참조 ID에 직접 넣지 않는다.

연결부가 만드는 참조는 Repository·SourceRevision·Module·ModuleBuild·Artifact·AnalysisSnapshot 여섯 종류다. 메서드 목록과 제공되지 않은 서비스·배포·런타임·Trace 정보는 가져오거나 추론하지 않는다. `require_exact_bridge`는 다섯 빌드 필드와 색인·설정 해시의 정확한 선택을 강제한다.

실행:

```sh
python3 -m unittest experiments.evidence_model_lab.test_model -v
python3 -m experiments.evidence_model_lab.run --output /tmp/evidence-model-report.json
```

리포트의 `BDD-MDL-*` 케이스는 기대값과 실제 판정을 독립적으로 적는다. Gherkin 명세 자체를 실행하는 수락 테스트와는 구분한다.

`QueryRequest`는 조직, 주어, 관계, 두 시간 시점, 허용 참조를 받고 근거 종류와 표시량 상한을 지정할 수 있다. 기본 `visibility_complete=False`는 세부정보 없이 `INCOMPLETE_VISIBILITY`를 반환한다. `True`는 호출자가 제공한 참조 범위의 완전성을 선언하는 값이다. 이 경우 그 범위의 주장만으로 결과·충돌·상한을 계산하며, 범위 밖 주장의 유무에 따라 응답을 바꾸지 않는다. 주어가 허용되지 않은 요청도 일반적인 불완전 응답을 반환한다. 실제 인증·인가는 별도로 구현해야 한다.

`QueryResult.claims`는 출처·근거 종류·두 시간 축을 포함한 조회용 주장이다. 정정·철회 연결 ID는 허용 여부와 관계없이 일괄 생략하며 해당 필드는 `None`이다. 원장의 원본은 보존한다. 따라서 조회용 주장을 원장에 재입력하면 안 된다.

기존 PostgreSQL 분석을 읽는 `verify_store`는 기존 Psycopg 실행 환경을 사용한다. 새 스키마나 분석을 발행하지 않으며, 서버에서 읽기 전용으로 강제한 트랜잭션으로 원본 JSON과 메타데이터 연결을 대조한다. [실행 명령과 결과](../../docs/experiments/EVIDENCE-MODEL-RESULTS.md)에서 단위 시험, 합성 시나리오, 실제 DB 읽기 검증을 구분한다.
