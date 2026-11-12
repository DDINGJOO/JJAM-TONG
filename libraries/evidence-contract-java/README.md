# 버전 근거 계약 Java 실험 라이브러리

분석한 빌드와 실행 측에서 제공한 빌드 정보가 같은지 비교한다. **메서드 분석기나 자동 계측 agent는 아니다.** 외부 의존성 없이 Java 17 이상에서 사용하는 초기 API이며, 공개 호환성을 보장하는 제품 규격은 아직 없다.

## 빌드와 검증

Python 3와 JDK 17 이상이 필요하다. `JDK_HOME`은 사용할 JDK의 설치 경로로 지정한다. 저장소 루트에서 실행한다.

```sh
python3 libraries/evidence-contract-java/build.py --java-home "$JDK_HOME"
```

저장소 기준으로 `libraries/evidence-contract-java/build/evidence-contract.jar`와 같은 디렉터리의 `verification.json`이 생긴다. 컴파일은 `--release 17 -Xlint:all -Werror`를 사용한다. 테스트도 생성한 JAR에 의존해 별도로 컴파일하고 실행한다. Maven·Gradle이나 외부 패키지를 설치하지 않는다. JAR 생성 시각 때문에 반복 빌드의 바이트가 같다는 보장은 없다.

## 제공하는 계약

| API | 책임 |
| --- | --- |
| `BuildIdentity` | 저장소·revision·빌드·모듈·최종 산출물 SHA-256 식별 정보를 보관 |
| `AnalysisIdentity` | 대상 빌드와 분석 실행·분석기 이름/버전·스키마 버전·설정/인덱스 해시를 보관 |
| `EvidenceLinker.compare` | 호출자가 명시적으로 선택한 분석과 실행 측 빌드 정보의 일치 여부를 비교 |
| `ArtifactDigests.sha256` | 완성된 파일의 SHA-256 해시를 계산 |

SHA-256은 파일 내용에서 계산하는 해시다. 해시만으로 저장소 출처나 실제 실행 사실을 인증하지 않는다. revision 등 문자열은 공백만 있는 값을 거부하며, 해시의 대소문자를 제외하면 입력을 그대로 비교한다. GitHub·CI 제품별 식별자를 필수 형식으로 요구하지 않는다.

```java
import io.jjamtong.evidence.*;
import java.nio.file.Path;
import java.util.Optional;

// repository/revision/build/module은 빌드 파이프라인이 확인해 전달할 값이다.
var build = new BuildIdentity(repository, revision, buildId, module,
        ArtifactDigests.sha256(Path.of(finalArtifactPath)));

// 아직 대응하는 분석 결과를 수집하지 않았다면 분석을 만들어 넣지 않는다.
var result = EvidenceLinker.compare(Optional.empty(), Optional.of(build));
// result.status() == UNRESOLVED, result.fields() == Set.of("analysis")
```

필수 정보를 모르면 완전한 식별자를 만들지 않고 `Optional.empty()`로 전달한다. `unknown`, `latest`, 추측한 커밋 등을 대체 값으로 채우지 않는다. 원본의 진위와 완전성은 연동 도구가 확인할 책임이며, 이 API가 문자열의 출처까지 확인하지는 않는다.

| 결과 | 의미 |
| --- | --- |
| `MATCH` | 제공한 두 빌드의 다섯 필드가 모두 같음. 실제 실행·출처 인증·분석 스키마 지원을 뜻하지 않음 |
| `MISMATCH` | 빌드 필드가 다름. `fields`에 다른 필드 이름을 반환 |
| `UNRESOLVED` | 분석 또는 실행 측 식별 정보가 없음. `fields`에 없는 쪽을 반환 |

같은 빌드를 다른 설정으로 분석하면 분석 식별자는 별개다. 비교 결과는 호출자가 선택한 분석을 그대로 보존한다. 최신 분석 자동 선택, 스키마 호환성 판단, 저장·조회·권한·보존 정책은 이 라이브러리에서 구현하지 않는다.

## 검증 근거와 적용 경계

JDK 17·21에서 각각 23개 계약 검증을 통과했다. JDK 17로 만든 JAR을 별도 소비자 코드에서 JDK 21로 컴파일·실행한 검증도 통과했다. [실행 기록](../../docs/experiments/library-contract-results.json)과 [ADR 0002](../../docs/decisions/0002-experimental-build-identity.md)에 조건을 남긴다. 이는 기존 47개 Draft BDD의 실행 완료를 뜻하지 않는다.

최종 앱 JAR을 만든 뒤 외부 파일에 식별 정보를 남기는 방식을 적용한다. 이 외부 파일을 sidecar manifest라 부른다. 앱 내부에 최종 앱 JAR 전체의 해시를 넣으면 파일 자체가 바뀌므로, 전체 해시를 그 파일 안에 다시 넣지 않는다. 앱 시작 시 실제 파일과 sidecar의 해시를 대조하는 것은 대상 프로젝트의 연동 책임이다. 해시를 계산하는 동안 파일이 바뀌지 않아야 한다.

별도 MSA 대상에 JAR을 적용한 [로컬 검증 결과](../../docs/experiments/LOCAL-MSA-TARGET.md)를 남겼다. 후속 [자동 메서드 분석·OTel 실행 연결](../../docs/experiments/METHOD-OBSERVABILITY-RESULTS.md)은 별도 도구에서 비교하며 [T25 #44](https://github.com/DDINGJOO/JJAM-TONG/issues/44)로 관리한다. 이 계약 JAR 자체에는 분석기·계측 agent를 포함하지 않는다.
