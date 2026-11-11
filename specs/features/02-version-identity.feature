@draft @required
Feature: 코드 분석과 실행 근거의 버전을 명확히 식별한다

  Scenario: BDD-VER-001 분석 결과에서 대상과 분석 조건을 추적한다
    Given 합성 저장소 shop의 build-A를 분석한다
    When 분석 결과가 조회 가능해진다
    Then 다음 식별 정보를 조회할 수 있다
      | 구분 | 식별 정보 |
      | 코드 | repository identity, commit, build, module |
      | 분석 | analysis run, index digest, analyzer version |
      | 조건 | schema version, config identity |
    And 출처와 분석 대상 시점과 수집 시점을 확인할 수 있다

  Scenario: BDD-VER-002 같은 버전 문자열의 다른 빌드를 합치지 않는다
    Given build-A와 build-B가 같은 앱 버전 문자열을 사용하지만 산출물이 다르다
    When 두 빌드의 동일한 메서드 이름에 실행 기록이 생긴다
    Then 각 실행 기록은 일치하는 빌드와 메서드의 분석 결과에 연결된다
    And 같은 버전 문자열 또는 브랜치 이름만으로 관계를 합치지 않는다

  Scenario: BDD-VER-003 버전 불일치와 재분석을 명시한다
    Given build-A의 실행 기록과 build-B의 코드 지도만 있다
    And 같은 커밋도 다른 분석 설정으로 재분석될 수 있다
    When 에이전트가 실행 기록에 대응하는 코드 근거를 요청한다
    Then 일치하는 지도 없음 또는 불일치 상태와 비교한 식별 정보를 반환한다
    And 최신 브랜치 지도로 대체하거나 다른 분석 실행을 덮어쓰지 않는다
