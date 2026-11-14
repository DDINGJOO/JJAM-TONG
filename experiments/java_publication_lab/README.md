# Java 결과 발행 표현 비교

이 실험은 이미 생성한 Java `jjamtong.methods.v1` 결과를 로컬 파일 표현으로만 비교한다. DB, 브라우저, 라이브 GitHub 또는 실제 서비스에 발행하지 않으며, 결과는 합성 fixture의 메타데이터·해시·집계 수치만 기록한다.

이 비교의 기준 코드는 `7748983c75f988fd94acdc6b70101581e51ed873`의 분석기 0.2.2다. 해당 생산자와 이 실험실을 함께 사용한다. 이후 생산자 버전이 바뀌면 프로브는 명시적으로 거부하므로 기존 결과의 재현 시 기준 버전을 확인한다. 먼저 Java 분석기와 합성 fixture를 준비한다. fixture는 검증용 합성 입력을 뜻한다.

```sh
python3 tools/java-call-analysis/build.py
python3 - <<'PY'
from pathlib import Path
from experiments.analysis_reuse.run import scale_fixture
scale_fixture(Path('.local/java-publication/scale-400000'), Path('/path/to/jdk'),
              400000, 'scale-fixture')
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
