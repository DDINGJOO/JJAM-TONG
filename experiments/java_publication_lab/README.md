# Java 결과의 저장 표현과 로컬 통합 검증

이 실험실은 Java `jjamtong.methods.v1` 결과의 저장 표현 비교와 선택한 표현의 로컬 통합 검증을 나눈다. `run`은 파일만 비교한다. `integration`은 명시적으로 지정한 로컬 PostgreSQL에 합성 분석을 저장하며, 브라우저 QA는 별도로 수행한다. 라이브 GitHub나 실제 서비스에는 발행하지 않는다.

이 비교의 기준 코드는 `7748983c75f988fd94acdc6b70101581e51ed873`의 분석기 0.2.2다. 프로브는 Git의 해당 커밋에서 Java 소스 전체를 읽어 격리 컴파일한다. 현재 생산자의 클래스 파일을 사용하지 않는다. 해당 커밋을 로컬 Git에서 읽을 수 있어야 한다. 직접 의존성의 역사적 고정 해시, 현재 빌드 명세와 실행 JAR 전체의 목록·해시를 확인한다. 현재 명세는 과거 전이 의존성의 잠금 파일이 아니며 실제 사용한 전체 해시는 결과에 기록한다. 먼저 Java 분석기와 합성 fixture를 준비한다. fixture는 검증용 합성 입력을 뜻한다.

```sh
python3 tools/java-call-analysis/build.py
python3 - <<'PY'
from pathlib import Path
from experiments.analysis_reuse.run import scale_fixture
scale_fixture(Path('.local/java-publication/scale-400000'), Path('/path/to/jdk'),
              400000, 'scale-400000')
PY
```

32 MiB 제한을 확인할 때는 production `Main.java`를 수정하지 않고, 한 곳의 발행 호출과 adapter version만 바꾼 격리 복사본을 컴파일·실행한다. `--java-home`은 JDK 17 또는 21 홈이어야 한다.

```sh
python3 -m experiments.java_publication_lab.probe \
  --fixture .local/java-publication/scale-400000 \
  --output .local/java-publication/probe \
  --java-home /path/to/jdk
```

이미 있는 probe 결과는 Java를 다시 실행하지 않고 비교할 수 있다.

```sh
python3 -m experiments.java_publication_lab.run \
  --analysis .local/java-publication/probe/methods.json \
  --fixture .local/java-publication/scale-400000 \
  --output .local/java-publication/comparison
python3 -m unittest experiments.java_publication_lab.test_formats \
  experiments.analysis_job_lab.test_model experiments.analysis_job_lab.test_publication experiments.analysis_job_lab.test_run -v
```

비교기는 들여쓰기 JSON을 10 MiB와 32 MiB 경계로 판정하고, 10 MiB 제한의 공백을 줄인 JSON과 전체 64 MiB·조각당 1 MiB의 분할 결과를 다시 읽는다. 세 경우 논리 JSON과 생성한 색인의 SHA-256 해시가 정확히 같아야 한다. 색인의 들여쓰기·기본 공백·공백 제거 표현별 크기와 현재 `save_index`·`prepare` 경계도 기록한다. 입력 키는 빌드·입력·설정·출처·메타데이터 해시를 정규화한 로컬 비교용 값이며 공통 작업 입력 규격이나 출처 인증이 아니다.

같은 실제 결과의 분할 재발행, 다른 입력·시도, 조각 누락·손상, 전체 수신 예산 초과를 검사한다. 작은 동일 계약의 단위 시험은 동시 발행·중단·전체 발행 예산도 다룬다. 출력 경로는 비어 있어야 하며 이미 완료한 비교를 덮어쓰지 않는다. 바이트 상한은 직렬화·저장 경계이며 임의 규모, JVM 힙이나 운영 수용량을 보장하지 않는다. 한 프로세스의 단일 측정값은 형식별 성능 순위가 아니다.

## 선택한 공백 표현을 실제 DB에 연결한다

[로컬 DB 준비](../../tools/evidence_store/README.md#로컬에서-실행한다)의 기존 가상 환경·고정 의존성과 합성 전용 PostgreSQL을 사용한다. `PYTHON`과 `JJAMTONG_EVIDENCE_DSN`은 그 안내에 따라 명시적으로 설정한다. 이 실행은 해당 DB에 스키마를 초기화하고 지정한 조직 라벨에 합성 이전·새 빌드를 저장한다. 새 분석 ID를 발행하며 기존 분석은 덮어쓰지 않는다.

앞에서 만든 이전 입력에 대응하는 새 빌드를 준비한다. 같은 모듈에서 `m19`와 호출부를 `m19Updated`로 바꾼 검증용 입력이다.

```sh
python3 - <<'PY'
from pathlib import Path
from experiments.analysis_reuse.run import scale_fixture
scale_fixture(Path('.local/java-publication/scale-400000-changed'), Path('/path/to/jdk'),
              400000, 'scale-400000', variant=True)
PY
"$PYTHON" -m experiments.java_publication_lab.integration \
  --old-fixture .local/java-publication/scale-400000 \
  --new-fixture .local/java-publication/scale-400000-changed \
  --java-home /path/to/jdk \
  --output .local/java-publication/integration \
  --tenant java-publication-local
```

분석기 `0.2.3`의 색인 저장·재읽기·DB 전체 대조·같은 해시 재시도·다른 해시 거부·기존 이력 보존을 검사한다. 생산자의 JAR·Java 소스 전체·실행 의존성을 실행 전후에 확인한다. 각 출력 디렉터리는 새 경로이거나 비어 있어야 한다. 같은 조직 라벨·분석 ID의 다른 입력은 충돌하므로 다른 입력의 반복 실행에는 새 조직 라벨을 지정한다. 이전·새 빌드 각각의 발행은 원자적이며 두 빌드 전체를 하나의 트랜잭션으로 묶지는 않는다.

공개 기준 결과와 정확히 같은 Corretto 21.0.11 입력을 재현했다면, 다음 두 인수를 **함께** 추가해 역사적 생산자와 전체 JSON·소스 위치를 대조할 수 있다.

```text
--baseline .local/java-publication/probe/methods.json
--baseline-record docs/experiments/java-publication-comparison-results.json
```

공개 기록은 지정한 역사적 커밋·버전·입력·파일 해시를 모두 요구한다. JDK·소스·빌드가 다르면 정당하게 거부될 수 있다. 두 인수를 생략한 통합 실행은 DB 경로를 검증하지만 역사적 기준과의 동일성을 판정하지 않는다. 공개 결과의 현재 생산자 JAR 해시는 재현 실행의 바이너리 해시와 다를 수 있다. Maven의 빌드 시각 등 패키징 정보가 바뀔 수 있으므로 재현 실행은 자신이 검사한 JAR·전체 의존성 해시를 새로 기록한다.

생성하는 `synthetic-otlp.log`는 부모 누락과 버전 불일치를 확인하기 위한 **합성 OTLP 기록**이다. 실제 앱을 실행하거나 요청을 캡처하지 않는다. 같은 `PYTHON`·DSN으로 화면을 실행한 뒤 빌드 전환·검색·그래프·오류·부분 결과를 브라우저에서 따로 확인한다.

```sh
"$PYTHON" -m tools.evidence_web --tenant java-publication-local --port 28741 \
  --trace-log .local/java-publication/integration/synthetic-otlp.log \
  --telemetry-config cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
"$PYTHON" -m unittest experiments.java_publication_lab.test_probe \
  experiments.java_publication_lab.test_integration -v
```

사용 중인 포트가 있으면 별도 포트를 선택한다. `integration.json`의 `browserQa: pending`은 이 CLI가 브라우저를 검사하지 않는다는 뜻이다. 실제 [통합 결과](../../docs/experiments/JAVA-COMPACT-INTEGRATION.md)는 별도 브라우저 관찰·캡처를 묶어 최종 판정을 남긴다. GitHub Actions 포장의 `method-fixture` 제한과 각 단계의 상한은 확대하지 않는다.
