# 정확 입력 Java 분석 재사용

기존 [JavaParser·WALA 분석기](../java-call-analysis/README.md)의 **전체 결과**를 입력이 같은 경우에 재사용하는 로컬 CLI다. 소스나 JAR이 달라지면 전체 분석을 실행한다. 변경된 메서드만 분석하는 기능은 제공하지 않는다.

```sh
python3 -m tools.analysis_reuse \
  --tenant local-example --cache /path/to/cache \
  --java-home /path/to/jdk21 \
  --source-root /path/to/src/main/java --artifact /path/to/application.jar \
  --metadata /path/to/build-manifest.json --module application \
  --include-package example.application --entrypoint example.application.Main \
  --output /path/to/new-analysis.json
```

기존 분석기 JAR과 의존성, JDK 17 또는 21이 필요하다. 현재 파일 잠금은 POSIX의 `flock`을 사용하므로 macOS·Linux의 로컬 파일시스템을 대상으로 한다. Windows와 공유 네트워크 파일시스템은 지원 검증 대상이다. Spring Boot 입력은 기존 분석기와 같이 JDK 21에서 `--artifact-format spring-boot --entrypoint-policy all-included-methods`를 명시한다. Boot 모드는 이번 재사용 통합 실험에서 실행하지 않았다.

메타데이터는 [기존 빌드 명세](../method_evidence/README.md)와 같은 `repository`, `revision`, `build`, `module`, `artifactSha256`, `sourceState: clean`, 전체 `sourceFiles` 목록을 가진다. 각 파일에는 상대 경로 `path`와 `sha256`이 필요하다. 이것은 호출자가 제공한 명세와 현재 바이트의 대조이며, 서명된 빌드 출처 증명이나 소스와 JAR의 컴파일 일치 증명은 아니다.

표준 출력은 JSON 실행 결과만 반환한다. 분석기 메시지는 표준 오류로 보낸다. `status`는 새 분석인 `analyzed` 또는 검증한 재사용인 `reused`다. 결과에는 `cacheKey`, 입력 확인·분석·발행 시간, 출력 바이트 수가 담긴다. 재사용해도 입력과 도구를 다시 읽으므로 비용이 발생한다.

키에는 조직 라벨·저장소·모듈, 전체 Java 소스와 원본 JAR 해시, 포함·제외 패키지와 시작점 정책, Python·재사용 코드·분석기·의존 JAR·JDK 파일의 해시가 들어간다. 실행 파일 경로도 포함하므로 다른 설치 경로의 동일 도구 사이에는 재사용되지 않을 수 있다. 빌드·커밋은 키에서 제외하고 현재 요청의 검증된 명세를 결과에 다시 붙인다. 기존 분석기가 이 명세를 그래프 계산에 사용하지 않는다는 계약을 전제로 한다.

손상된 캐시, 불완전한 분석 결과, 실행 중 입력 변경, 이미 존재하는 출력은 실패한다. 같은 키의 동시 요청은 파일 잠금 뒤 캐시를 다시 확인하며, 잠금 대기 상한은 75초다. JVM의 기존 1 GiB 힙·60초 제한과 결과 10 MiB 제한은 유지한다. JSON 명세·캐시·결과 읽기도 10 MiB로 제한한다. 출력은 새로운 경로에 원자적으로 생성하고, 실패한 요청은 성공 결과를 발행하지 않는다.

캐시 경로는 신뢰할 수 있는 로컬 작업 공간에 둔다. 해시는 손상을 탐지하지만 공격자가 바꾼 결과의 진위를 인증하지 않는다. 조직 라벨은 인증·인가 경계가 아니다. 원격 캐시·다중 조직 운영·보존과 삭제·배포는 별도 구현 대상이다. 기존 GitHub 수집기, Boot 발행 도구, DB와 화면은 이 CLI를 아직 호출하지 않는다.

```sh
python3 -m unittest tools.analysis_reuse.test_reuse -v
python3 -m experiments.analysis_reuse.run \
  --java-home /path/to/jdk21 --output /path/to/new-owned-directory --modular
```

두 번째 명령은 합성 Java를 생성하고 컴파일한 뒤 실제 분석기를 실행한다. 출력 디렉터리는 새 경로여야 한다. [설계 결정](../../docs/decisions/0008-exact-input-analysis-reuse.md), [복잡 구조 요구](../../docs/requirements/CODE-ANALYSIS-SCALE.md), [실측 결과](../../docs/experiments/ANALYSIS-REUSE-RESULTS.md)를 함께 읽는다.
