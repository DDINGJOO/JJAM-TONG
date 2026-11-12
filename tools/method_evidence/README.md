# 버전별 메서드 근거 연결 도구

정적 분석 결과와 실제 OTel span을 **지정한 빌드·분석 실행에만 연결하는 로컬 실험 CLI**다. Python 표준 라이브러리만 사용한다. [Java 빌드 계약](../../libraries/evidence-contract-java/README.md)의 다섯 식별 필드를 따르며, 제품 API·인증·보존 서버는 구현하지 않는다.

`span`은 한 작업의 추적 기록이다. 정적 호출 후보와 span의 부모 관계를 따로 보관한다. 부모 관계는 전달된 실행 문맥이며 동기 메서드 호출의 증명으로 바꾸지 않는다.

## 색인 생성과 정확한 이력 조회

저장소 루트에서 실행한다. 경로는 별도 대상 프로젝트에서 만든 실제 입력으로 지정한다.

```sh
python3 -m tools.method_evidence index \
  --analysis "$ANALYSIS_JSON" --manifest "$MANIFEST_JSON" \
  --artifact "$APP_JAR" --sources "$EFFECTIVE_SOURCES" \
  --store .local/method-indexes --run-id analysis-A

python3 -m tools.method_evidence query \
  --store .local/method-indexes --run-id analysis-A \
  --log "$OTLP_LOG" --trace-id "$TRACE_ID" \
  --telemetry-config "$TELEMETRY_CONFIG_SHA256"

python3 -m unittest tools.method_evidence.test_evidence -v
```

색인을 만들 때 실제 JAR·소스 파일 해시와 clean 상태의 빌드 manifest를 대조한다. manifest는 빌드 정보를 담은 외부 파일이다. 다섯 필드는 `repository`, `revision`, `build`, `module`, `artifactSha256`이다. 분석 실행 ID, 분석 도구·스키마·설정, 색인 해시도 함께 보관한다. 동일 ID에는 덮어쓰지 않고 완성된 파일을 원자적으로 공개한다. `latest`를 자동 선택하지 않으며, 없는 이력은 `HISTORY_NOT_COLLECTED`로 반환한다.

이 대조는 **호출자가 제공한 manifest와 로컬 파일의 일치**를 확인한다. 빌드 출처를 인증하거나 원격 프로세스가 그 JAR을 실행한다는 사실까지 입증하지 않는다.

## 수집·심벌 판정

OTel Java agent 2.33.1의 `logging-otlp` 출력에서 단일 `ResourceSpans` JSON을 읽는다. 저장 허용 항목은 빌드·계측 설정 식별, trace/span/parent ID, 메서드 이름, 시각, 오류 여부와 span link의 ID다. 인수·반환 본문·SQL·URL·예외 본문은 저장하지 않는다. 독립된 실제 기능 결과와 [원문 근거](../../docs/experiments/METHOD-OBSERVABILITY-RESULTS.md)를 함께 확인한다.

| 상황 | 반환 의미 |
| --- | --- |
| 빌드 다섯 필드 일치, 지정한 계측 설정 일치 | 수집된 실행 근거를 반환 |
| 빌드가 다름 | `MISMATCH`; 다른 빌드의 메서드로 연결하지 않음 |
| 식별·계측 설정 누락 또는 올바르지 않은 설정 해시 | `UNRESOLVED` |
| 같은 클래스·이름에 선언 후보 하나 | `unique-name-resolved`; descriptor는 이 색인의 유일한 후보에서 유도했음을 표기 |
| 같은 이름의 overload가 여러 개 | `UNRESOLVED_CODE_SYMBOL`; 후보를 남기고 선택하지 않음 |
| 부모 미수집·범위 밖, 저장 상한 초과 | `PARTIAL`; 알려진 이유를 보존 |

OTel은 JVM descriptor, 즉 인수·반환 타입 식별을 이 메서드 span에 넣지 않는다. 관측 상태 `OBSERVED`도 모든 span의 정확한 선언을 알아냈거나 수집이 완전하다는 뜻이 아니다. `symbolStatus`와 독립 기대 호출 수를 함께 확인해야 한다.

파일 입력은 10MiB, 조회에 남길 기록은 trace당 기본 100개로 제한한다. 이는 **저장 단계의 제한**이며 앱의 span 생성량·SDK 큐·프로세스 상주 메모리(RSS)를 제한하지 않는다. 기록이 없다는 사실만으로 미실행·sampling·전송 유실의 원인을 판별하지 않는다.
