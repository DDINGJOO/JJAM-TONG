# 빌드 발견과 기준선 비교 도구

Maven·Gradle의 모듈 후보를 읽고, 소유자가 제공한 공통 명세의 파일을 검사하며, 정확히 선택한 두 기록을 비교한다. 파이썬 표준 라이브러리를 사용한다. 발견 과정에서 빌드 스크립트를 실행하지 않는다.

명세와 제한은 [빌드 명세 계약](../../docs/requirements/BUILD-INVENTORY.md), 선택 이유는 [ADR 0013](../../docs/decisions/0013-build-inventory-baselines.md)에 있다. 실제 입력을 생산할 Maven·Gradle 플러그인, 분석 작업 자동 예약, 웹 화면 연결은 별도 구현 대상이다.

```sh
python3 -m tools.build_inventory --help
python3 -m tools.build_inventory discover --root /absolute/authorized/repo --adapter gradle
python3 -m tools.build_inventory capture --root /absolute/authorized/repo \
  --manifest build-manifest.json --tenant local-example --output /absolute/output/baseline.json
python3 -m tools.build_inventory inspect --snapshot /absolute/output/baseline.json
```

`--root`는 심볼릭 링크를 거치지 않는 명시적인 절대 루트다. `--manifest`는 그 루트에 대한 상대 경로이며, 파일 입력도 같은 루트 아래에 있어야 한다. 출력 디렉터리는 먼저 준비하고 기존 기록과 다른 파일명을 지정한다. 후보 발견 결과와 검증용 명세는 서로 다른 형식이다.

```sh
python3 -m tools.build_inventory compare \
  --baseline /absolute/output/baseline.json --current /absolute/output/current.json \
  --baseline-sha256 '<baseline manifestSha256>' \
  --current-sha256 '<current manifestSha256>' --limit 100
```

비교는 명세 해시 두 개를 필수로 받으며 최신 기록으로 대체하지 않는다. 검사 기록의 별도 해시와 두 시각도 출력한다. `DECLARED` 모드의 경로는 모듈 의존 선언의 영향 후보다. 실제 요청 Trace나 모든 메서드의 호출 흐름을 의미하지 않는다. 미수집 입력과 표시·탐색 상한은 부분 결과로 설명한다.

```sh
python3 -m tools.build_inventory link \
  --snapshot /absolute/output/baseline.json --index /absolute/input/index.json \
  --module board-api --artifact .local/artifacts/build-1/board-api.jar \
  --index-sha256 '<indexSha256>' --config-sha256 '<configSha256>'
```

연결은 기존 분석의 메타데이터만 확인한다. 모듈·산출물과 다섯 빌드 필드, 색인·설정 해시가 모두 일치해야 한다. CLI의 JSON 입력·출력 상한은 10 MiB다. 큰 분석본의 운영용 로딩·조회 경로를 이 명령으로 대체하지 않는다.

시험과 로컬 실험:

```sh
python3 -m unittest tools.build_inventory.test_inventory \
  tools.build_inventory.test_discovery tools.build_inventory.test_baseline \
  experiments.build_inventory_lab.test_run -v
python3 -m experiments.build_inventory_lab.run --output /absolute/output/build-inventory-run.json
```

실험은 합성 바이트 파일과 명시적인 의존 관계를 사용한다. 이미 보존된 공개 대상의 산출물과 분석본을 추가로 읽는 방법은 [실험실](../../experiments/build_inventory_lab/README.md)에 있다. 대상 업무 코드를 이 저장소에 복사하지 않는다.
