# 빌드 명세와 기준선 비교 검증 결과

검증일: 2026-11-14. [#78](https://github.com/DDINGJOO/JJAM-TONG/issues/78)·[계약](../requirements/BUILD-INVENTORY.md)·[ADR 0013](../decisions/0013-build-inventory-baselines.md)·[실험실](../../experiments/build_inventory_lab/README.md)·[기계 판정](build-inventory-results.json).

빌드 설정에서 모듈 후보를 찾고, 별도 명세의 파일을 검사한 뒤 두 기록의 선언 차이를 비교했다. 실제 배포·Trace 자동 수집이나 전체 메서드 그래프의 증분 분석을 완료한 결과는 아니다.

## 실행과 판정

| 검사 | 결과 | 범위 |
| --- | --- | --- |
| 새 단위 시험 | 44개 통과 | 명세·불변 기록·안전한 파일 읽기·발견·기준선·부분 근거·작업 상한 |
| 합성 실험 | 8/8 판정 일치 | 모듈 후보, 해시·기준선 불일치 거부, 독립적인 이전·현재 영향 경로, 부분 목록, 과거 기록 재조회 |
| 보존된 공개 대상 | 7/7 판정 일치 | 루트 포함 POM 7개, 두 JAR·입력 해시, 기존 분석 메타데이터 일치와 잘못된 색인 해시 거부, 부분 상태, Git 상태 보존 |
| 기존 회귀 검사 | 83개 중 63개 통과·20개 건너뜀 | 근거 모델·분석 재사용·저장 계약·웹·연동. DB 설정이 필요한 시험 20개는 이번 실행에서 건너뜀 |

합성·공개 대상 15건은 실행기가 `expected`와 `actual`을 대조한 판정이다. [Gherkin 행동 명세](../../specs/features/14-build-inventory.feature)를 실행한 결과와는 구분한다. 단위 시험에서는 기대 경로·상태를 리터럴 fixture로 지정하며, 실제 반환값으로 기대 결과를 만들지 않는다.

```sh
python3 -m unittest tools.build_inventory.test_inventory \
  tools.build_inventory.test_discovery tools.build_inventory.test_baseline \
  experiments.build_inventory_lab.test_run -v
python3 -m experiments.build_inventory_lab.run --output /absolute/output/synthetic-run.json
```

기존 회귀 검사는 이미 Psycopg가 준비된 로컬 실행 환경을 사용했다. 시스템 Python에서는 이 기존 의존성이 없어 웹 시험을 import하지 못했으며, 환경을 맞춰 재실행했다. 새 의존성을 설치하지 않았다. DB 설정을 제공하지 않은 시험을 통과로 세지 않는다.

## 공개 산출물과 역사적 근거의 범위

공개 대상은 별도 [JJAM-TONG-playground](https://github.com/DDINGJOO/JJAM-TONG-playground)다. 두 기록의 소스 버전은 `0ea6a6845550a86114c28bcbf660723ac3575561`이며 빌드는 `boot-evidence-b1`, `boot-evidence-b2`다. 각 빌드에서 JAR 1개와 기록된 소스 9개의 해시를 읽어 확인했다. 산출물·분석 색인·설정 해시는 기계 판정에 보존했다.

원본 명세에 남아 있던 소스 해시와 현재 읽을 수 있는 파일이 일치하는 범위만 연결했다. 과거 소스가 현재 소스와 같다고 임의로 치환하지 않았다. 이번 명세의 `recordedAt`과 `verifiedAt`은 이번 실행에서 얻은 시각이며, 과거 당시 수집했다는 증명이 아니다.

모든 모듈의 입력과 classpath·도구체인·생성 소스·빌드 조건을 보존한 자료는 없으므로 새 명세는 부분 수집 상태다. 두 빌드의 비교도 `PARTIAL`이다. 소스 해시가 같은 재빌드에서 산출물이 달라졌다는 사실을 소스 변경이나 성능 회귀로 바꾸지 않는다. 새로운 Java 분석, 앱 요청, DB 쓰기와 대상 코드 변경은 수행하지 않았다.

## 검증 중 수정한 경계

저장 기록을 여는 API의 불일치는 실제 소비자 호출로 재현해 수정했다. 발견 시험에는 모의 파일뿐 아니라 실제 임시 디렉터리를 추가했다. 선택 가능한 설정 파일이 없을 때의 예외 변환, UTF-16 DTD 우회, 속성 기반 Maven 경로, Gradle의 접두 콜론 없는 ID와 따옴표 안의 쉼표, 알 수 없는 설정 코드의 누락을 회귀 시험으로 고정했다. 발견 상한은 출력 개수뿐 아니라 경로 확장 작업에도 적용한다. 공개용 입력은 별도의 명시적 루트에서 안전하게 읽으며, JSON 중복 키·크기와 Git 조회의 출력·시간 상한도 검사한다.

비교기에서는 미수집 의존 정보를 확정적인 연결 삭제로 표시하지 않도록 수정했다. 새로 추가되거나 제거된 모듈의 미수집 입력도 부분 상태에 반영한다. 빌드·소스 버전만 달라진 경우는 별도 식별 차이로 남기며, 역방향 탐색용 색인을 그래프별로 한 번 만들고 작업 예산을 함께 계산한다. 발견·검토·수정 근거는 [작업 이슈](https://github.com/DDINGJOO/JJAM-TONG/issues/78)에 연결했다.

## 앞으로 검증할 것

소유자가 실행하는 Maven·Gradle 명세 생산기, 완전한 컴파일 입력과 출처 증명, 실제 저장소의 분석 예약·메서드 차이, 영구 저장과 대규모 수용량이 필요하다. 이번 발견기는 UTF-8 설정과 명시한 리터럴 문법을 지원하며 동적 빌드의 평가 결과를 대신하지 않는다.

웹에서는 두 기록의 선택·해시·시각·부분 근거·이전/현재 경로를 함께 보여 줘야 한다. [화면 QA 계획](../requirements/BUILD-INVENTORY.md#화면과-qa-판정)은 남겼으나 새 웹 UI와 브라우저 QA는 이번 범위에 포함하지 않았다. [Datadog·Elastic 비교](../OSS-ARCHITECTURE-COMPARISON.md#9-datadog과-elastic은-코드와-실행을-어떻게-연결하는가)의 제품 설치·가상 스레드·Reactor·Kafka·적용 전후 성능도 별도 비교 대상이다. 과거 에이전트 정답표는 [#79](https://github.com/DDINGJOO/JJAM-TONG/issues/79)에서 당시 근거와 나중에 확인한 사실을 분리해 검증한다.
