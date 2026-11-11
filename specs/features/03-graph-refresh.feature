@draft @required
Feature: 코드가 바뀌면 관계 지도를 자동 갱신하고 과거 버전을 보존한다

  Scenario: BDD-UPD-001 메서드 추가와 삭제와 이름 변경을 반영한다
    Given build-A에는 validate와 legacyCheck가 있는 성공한 코드 지도가 있다
    When build-B에서 validate를 validateInput으로 바꾸고 notify를 추가하고 legacyCheck를 삭제한다
    And 합의한 변경 감지 조건으로 새 분석이 수행된다
    Then build-B 지도는 추가된 메서드와 바뀐 관계를 포함하고 삭제된 관계를 포함하지 않는다
    And build-A 지도는 기존 식별자로 보존되어 이전 배포의 근거로 조회된다

  Scenario: BDD-UPD-002 실패한 갱신이 성공한 지도를 훼손하지 않는다
    Given build-A의 성공한 지도와 build-B의 새 분석 요청이 있다
    When build-B 분석이 실패하거나 일부 모듈만 분석된다
    Then 실패 또는 부분 완료와 대상 빌드와 누락 범위를 조회할 수 있다
    And build-A 결과를 build-B의 성공한 최신 지도라고 표시하지 않는다

  Scenario: BDD-UPD-003 완료 순서와 무관하게 해당 배포의 지도를 선택한다
    Given build-A와 build-B의 분석이 동시에 진행되고 두 버전이 각각 배포된다
    When build-B 분석이 먼저 끝나고 build-A 분석이 나중에 끝난다
    Then 각 배포의 실행은 완료 순서가 아닌 해당 빌드의 지도에 연결된다
    And 재시도와 중복 완료가 다른 빌드의 결과를 덮어쓰지 않는다

  Scenario: BDD-UPD-004 CI 공급원을 바꿔도 같은 입력의 관계 의미를 보존한다
    Given 같은 합성 빌드 산출물과 분석기 및 스키마 및 설정이 두 CI 환경에 제공된다
    When 각 환경에서 분석을 실행하고 같은 빌드의 관계를 조회한다
    Then 빌드 연결과 정규화한 메서드 및 관계 집합이 일치한다
    And 분석 실행 식별자와 수집 시각과 CI 출처는 각각 보존한다
    And CI 전용 실행 번호만으로 공통 빌드 식별을 대체하지 않는다
