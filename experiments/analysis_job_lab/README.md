# 분석 작업·결과 발행 계약 실험

입력 버전·실행 시도·완료 상태를 분리하고, 같은 합성 레코드를 단일 파일과 분할 결과로 발행한다. Python 표준 라이브러리만 사용한다. 기존 Java 분석기·DB·CI·화면을 전환한 구현은 아니다.

```sh
python3 -m unittest experiments.analysis_job_lab.test_model experiments.analysis_job_lab.test_publication experiments.analysis_job_lab.test_run -v
python3 -m experiments.analysis_job_lab.run --output .local/analysis-job-example --records-per-stage 30000
```

출력 경로는 새 디렉터리여야 한다. 각 구성은 별도 프로세스로 실행한다. `single`과 `bundle`은 전체 결과 32 MiB·파일당 10 MiB라는 같은 예산을 사용한다. `single-expanded`는 파일당 상한만 32 MiB로 바꾸어 비교한다. 분할 방식의 조각은 최대 1 MiB이며 레코드·명세·조각 수에도 별도 제한을 둔다. 이 수치는 실험 조건이며 제품 정책이 아니다.

`AnalysisInput.key()`는 입력과 분석 조건을 식별한다. 재시도는 새 `Job.attempt`로 구분한다. 원본 JAR이 없는 언어는 해당 입력을 `not-applicable`로, 확보하지 못한 입력은 `unavailable`로 명시한다. 빈 집합을 실제로 확인해 얻은 해시와 구분한다. 소스 revision은 공급원의 불투명 식별자이며 Git SHA만 허용하지 않는다.

분할 결과는 `objects/<sha256>.jsonl`의 불변 조각과 `complete.json`의 완료 명세로 구성한다. 필수 단계·모든 조각·입력과 실행 시도·해시·순서·건수·바이트를 확인해야 완료를 인정한다. 조각만 남은 디렉터리는 완료가 아니다. 같은 내용의 중복 발행은 허용하고 기존 경로의 다른 내용은 거부한다. 소비자는 반복자를 끝까지 검증한 뒤 파생 데이터를 반영해야 한다.

전체 예산은 모든 조각과 완료 명세의 바이트를 포함한다. `verify_bundle`이 반환한 `VerifiedCompletion`만 `Job.finish`에 전달할 수 있다. 같은 모양의 raw 명세는 완료 증거가 아니다. 이 타입은 로컬 API의 오용 방지이며 인증 경계는 아니다. 비교 실행의 시간 초과는 구성별로 기록하며 완료 파일을 관측해도 검증하지 못한 결과는 성공으로 승인하지 않는다.

호출자가 소유한 신뢰하는 로컬 디렉터리에서 시험했다. 해시는 출처의 진위를 인증하지 않는다. `fsync`와 같은 파일시스템의 hard link를 사용하지만 전원 장애·다중 호스트·원격 객체 저장소의 내구성을 검증한 것은 아니다. 실패 후 남은 조각의 보존·정리는 후속 정책이다. 이 실험에는 네트워크 서비스·인증·조직 권한 검사가 없다.

바이트 제한은 발행·수신할 표현 크기의 제한이다. 호출자가 만든 레코드나 JSON 인코더의 큰 문자열 조각은 검사 전에 메모리를 사용할 수 있다. 분석기 전체 메모리·힙·프로세스·시간·동시 실행 제한을 대신하지 않는다. 취소·입력 재확인용 검사 지점도 협조적인 로컬 호출이며 멈춘 분석기나 분산 실행기의 소유권을 강제하지 않는다.

[공통 계약](../../docs/requirements/ANALYSIS-JOB.md) · [실측과 반례](../../docs/experiments/ANALYSIS-JOB-CONTRACT.md) · [ADR 0010](../../docs/decisions/0010-analysis-job-publication.md)
