@draft @required
Feature: 정적 메서드 관계와 실제 실행 관계를 구분한다

  Scenario: BDD-REL-001 포함 범위의 private self-call도 실행 근거와 대조한다
    Given 합성 앱 com.example.shop에서 place가 같은 클래스의 private validate를 호출한다
    And 정적 분석에는 place에서 reserve와 reject로 이어질 수 있는 후보 경로가 있다
    When 정상 주문 요청에서 place와 validate와 reserve가 관측된다
    Then 관측된 호출에는 해당 실행의 부모 관계와 메서드 식별자가 연결된다
    And reject 경로는 정적 후보로 남으며 실제 관측 경로로 표시되지 않는다

  Scenario: BDD-REL-002 같은 이름의 overload를 서로 다른 메서드로 식별한다
    Given OrderService에 place(String)과 place(String,int)가 있다
    When 요청이 place(String,int)만 실행한다
    Then 두 메서드는 모듈과 클래스와 JVM descriptor를 포함해 구분된다
    And 실행 근거는 place(String,int)에만 연결된다

  Scenario: BDD-REL-003 미해결 호출과 미관측을 실행 부재로 단정하지 않는다
    Given reflection 호출의 정적 대상은 미해결이다
    And 일부 메서드가 계측 범위 또는 샘플링 정책 때문에 관측되지 않는다
    When 에이전트가 해당 메서드의 관계와 실행 여부를 조회한다
    Then 정적 미해결과 실제 관측 여부와 알려진 수집 범위를 구분해 반환한다
    And 기록이 없다는 이유로 호출 불가능 또는 미실행이라고 확정하지 않는다

  Scenario: BDD-REL-004 언어와 런타임별 분석 지원 수준을 드러낸다
    Given 합성 서비스마다 언어와 런타임과 분석기 및 계측기의 지원 정보가 있다
    And 한 서비스는 정적 분석만 지원하고 다른 서비스의 메서드 분석은 미지원이다
    When 에이전트가 각 서비스의 메서드 관계와 실제 실행을 조회한다
    Then 지원 및 부분 지원 및 미지원 범위와 적용한 도구 및 설정 버전을 구분한다
    And 미지원 결과를 빈 관계 또는 실행 없음으로 바꾸거나 모든 언어에 JVM 식별 형식을 요구하지 않는다
