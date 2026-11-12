# 실행 모델과 문맥 경계 실험

별도 로컬 대상의 MVC 일반 스레드·가상 스레드·WebFlux/Netty와 Kafka 이벤트 경계를 비교한다. [ADR 0003](../../docs/decisions/0003-execution-model-comparison.md)에 범위를 정했다. 앱 업무 소스는 이 저장소에 복사하지 않는다. 수동 문맥 전달과 실제 스레드를 검증하며 자동 메서드 분석·계측을 제공하지 않는다.

## 실제 서버·Kafka 비교

[대상 기동 조건](../../docs/experiments/EXECUTION-MODEL-RESULTS.md#대상과-재현-조건)에 따라 별도 대상 앱을 실행한 뒤 다음 명령을 사용한다. 실행기가 앱·컨테이너를 시작하거나 종료하지 않는다.

```sh
python3 -m unittest experiments.execution_lab.test_oracles -v
python3 experiments/execution_lab/compare.py \
  --expected-target-revision 9f56f1d54c35ced8a5712efaadbe875a4d1aa5c4 \
  --output results/execution-comparison.json
```

각 구성에서 12개 요청의 문맥 분리, Kafka 재시도·중복·문맥 누락, 롤백·느린 DB·클라이언트 타임아웃을 검사한다. 누락된 문맥을 정상 연결로 판정하는 반례와 빌드 식별이 틀린 반례도 검사한다. 원시 결과에는 합성 문맥·이벤트 식별자가 포함된다.

## JDK별 monitor pinning 입력

같은 Java 21 클래스 파일에서 가상 스레드 4개가 각각 120ms 동안 대기한다. 각 작업이 자신의 monitor를 잡고 대기하는 입력과 monitor 없이 대기하는 대조 입력을 나눈다. JFR의 `VirtualThreadPinned`를 문턱값 0으로 활성화하고, 두 입력 모두 가상 스레드 시작·종료 4건을 확인한다. pinning 이벤트는 해당 `monitorPause`의 스택이 있는지도 구분한다.

```sh
python3 experiments/execution_lab/pinning.py \
  --java21 /path/to/jdk-21 \
  --java-new /path/to/jdk-25 \
  --output results/execution-pinning
```

JDK 21과 24 이상인 실제 설치 경로를 지정한다. 호스트에 JDK를 설치하거나 기존 앱을 변경하지 않는다. 원시 `.jfr`와 JSON을 지정한 출력 폴더에 저장한다. JFR에는 실행 환경 정보가 들어가므로 공개 결과는 필요한 합성 요약·해시만 기록한다.

[JEP 491](https://openjdk.org/jeps/491)이 개선한 `synchronized` 조건만 확인한다. 이 입력에서 pinning 이벤트가 없다고 모든 라이브러리·native callback의 pinning이 없다고 판정하지 않는다. 로컬 단회 실행이며 성능 순위·운영 처리량의 근거로 사용하지 않는다.

전체 실행 방법과 비교 결과는 [실험 기록](../../docs/experiments/EXECUTION-MODEL-RESULTS.md)에 있다.
