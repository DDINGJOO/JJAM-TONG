# 로컬 서비스 소스 탐색

외부 Java 프로젝트를 기동하지 않고 API 경로와 메서드별 정적 호출 후보를 읽는다. [#83](https://github.com/DDINGJOO/JJAM-TONG/issues/83)의 로컬 화면이며, 소스 선언을 실제 빌드·배포·요청 실행의 증거와 구분한다.

## 실행

기존 [Java 분석 도구](../java-call-analysis/README.md)의 캐시된 JavaParser 의존성과 JDK 21을 사용한다. 조회 서버는 기존 [근거 화면](../evidence_web/README.md)의 Python 환경을 재사용한다. 대상 앱이나 Gradle을 실행하지 않는다.

```sh
python3 -m tools.service_analysis.collect \
  --source /path/to/project \
  --output .local/service-page/private/snapshot.json \
  --java-home /path/to/jdk-21 \
  --label local-service

.local/storage-lab/venv/bin/python -m tools.service_analysis \
  --snapshot .local/service-page/private/snapshot.json \
  --port 28742
```

`http://127.0.0.1:28742/service-analysis`에서 읽는다. 기존 서버와 데이터를 바꾸지 않는다. 서버는 시작할 때 분석본 하나를 메모리에 올린다. Git 변경이나 파일 변경을 자동으로 재수집하지 않으므로 다른 분석본을 열려면 수집한 뒤 이 서버를 다시 실행한다. 이 경로의 저장 형태는 로컬 JSON이며 기존 PostgreSQL의 빌드 근거를 대체하지 않는다.

실제 프로젝트의 입력·결과·캡처는 Git에서 제외한 `.local/`에 보존한다. 소스 루트 `src/main/java`를 탐색하며 설정·비밀번호·요청 인수·반환 본문을 수집하지 않는다.

## 수집한 원본과 화면 표시

| 기능 | 의미 |
| --- | --- |
| API 탐색 | 지원하는 HTTP 매핑 선언과 진입 메서드를 연결한다. 경로·HTTP 메서드·컨트롤러·모듈로 검색한다. |
| 메서드 탐색 | 소스 선언을 보존하고 기본 목록에서 생성자·단순 접근자·고립된 비 API 선언을 숨긴다. 전체 보기로 복원한다. 호출 후보가 없는 API는 유지한다. |
| private 선언 표시 | Java `private` 선언의 화면 표시만 전환하며 플랫폼의 조회 권한은 바꾸지 않는다. 숨긴 선언 수를 표시하며 직접 호출 관계를 새로 만들지 않는다. |
| 호출 후보 | 깊이·노드·연결 수를 제한해 조회한다. 표시 상한에 따른 생략을 알린다. |
| 호출 조건 | 호출 위치마다 소스에 명시된 분기 문맥과 위치를 읽는다. 실행 사실을 뜻하지 않는다. |

기본 화면의 노이즈를 줄이는 것과 분석 데이터를 버리는 것은 다르다. 수집했지만 숨긴 선언과 분석하지 못한 선언을 구분한다. Lombok이 생성한 접근자처럼 소스에 없는 메서드는 소스 선언 수집으로 확보했다고 표현하지 않는다.

`if (allowed())`의 본문에 있는 호출과 `allowed()` 자체를 평가하는 호출도 구분한다. 전자는 참 분기의 본문에 있지만 후자는 분기를 결정하기 전에 실행된다. 조건에 포함된 문자열·문자·텍스트 블록 리터럴 값은 가린다. 이 정보는 전체 경로의 실행 가능성, 메서드 사이의 논리 조건이나 실제 요청의 분기 결과를 증명하지 않는다.

## 근거와 지원 경계

소스 해시, Git revision과 수정 여부, 수집 시각, 분석 정책과 비용을 기록한다. Java 수집기와 Python 실행 도구의 소스 해시도 남긴다. 이 해시는 실행에 사용한 의존성 바이너리나 대상 빌드의 출처를 인증하지 않는다. 이 식별은 소스 스냅샷이며, 기존 JAR이 이 소스와 일치하거나 배포됐다는 증거가 아니다. Spring의 빈 선택·프록시·리플렉션·동적 라우트와 실행 대상을 확정하지 않는다. 정상 추상 선언, 외부 호출 경계, 해석하지 못한 호출과 파싱 실패를 구분한다.

Repository 선언까지 해석한 관계와 실제 DB 접근은 별개다. Spring Data의 생성 구현이나 상속한 외부 메서드, Lombok 생성 코드를 소스 분석으로 완전히 확보했다고 주장하지 않는다. SDK를 필수로 도입하지 않으며 실제 등록 라우트·실행 증거·정확한 빌드와의 결합은 별도 검증 대상이다.

## 검증

```sh
.local/storage-lab/venv/bin/python -m unittest \
  tools.service_analysis.test_workspace \
  tools.service_analysis.test_collector_contract \
  tools.evidence_web.test_workspace -v
node --check tools/evidence_web/static/service.js
node --check tools/evidence_web/static/prototype.js
```

합성 소스의 예상 API·오버로드·private·분기 조건을 수집 결과와 대조하고, 실제 브라우저에서 선택·검색·필터 복원과 데스크톱·모바일 화면을 확인한다. 분석 시간·메모리·수집량을 기록하되 정확도나 기업 환경 지원 규모의 보장으로 쓰지 않는다. 정답 집합을 정한 분석 전략 비교는 [#82](https://github.com/DDINGJOO/JJAM-TONG/issues/82)의 범위다.
