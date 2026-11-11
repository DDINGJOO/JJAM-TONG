@draft @required
Feature: 서비스의 실행을 해당 시점의 배포와 인프라에 연결한다

  Scenario: BDD-INF-001 실행 시점에 유효한 배포와 워크로드 근거를 조회한다
    Given 합성 서비스의 빌드와 배포와 Pod UID와 노드 관계에 유효 시간과 출처가 있다
    When SRE가 특정 요청 시점의 인프라 문맥을 조회한다
    Then 해당 서비스와 환경과 배포와 워크로드 식별자를 시간 기준으로 연결한다
    And 관계의 출처와 수집 시점과 유효 기간을 함께 제공한다

  Scenario: BDD-INF-002 이름이 재사용된 Pod를 같은 자산으로 합치지 않는다
    Given 같은 namespace와 이름의 Pod가 재생성되어 서로 다른 UID를 가진다
    When 이전 Pod와 새 Pod의 실행 기록을 조회한다
    Then 실행 시점과 UID에 맞는 Pod와 노드 관계를 각각 제공한다
    And 현재 Pod 이름만으로 이전 실행을 새 자산에 연결하지 않는다

  Scenario: BDD-INF-003 누락된 인프라 관계로 원인을 확정하지 않는다
    Given 요청 지연과 노드 이벤트가 가까운 시각에 있으나 일부 관계 근거가 없다
    When 에이전트가 두 현상의 관련성을 조회한다
    Then 확인한 시간적 연관과 누락된 관계와 불확실성을 구분한다
    And 노드 이벤트가 지연의 원인이라고 자동 확정하지 않는다

  Scenario: BDD-INF-004 관측 대상의 실행 환경에 맞는 관계만 제공한다
    Given 같은 합성 앱 빌드를 실행하는 온프레미스 VM과 AWS EKS 및 ECS와 일반 Kubernetes가 있다
    And 각 환경에 서비스와 빌드 및 실행 근거가 수집되어 있다
    When 에이전트가 각 환경의 요청과 배포 문맥을 조회한다
    Then 환경별 실행 식별자와 공통 서비스 및 빌드 근거를 구분해 얻는다
    And VM에 없는 Pod 관계를 생성하거나 해당 없음 상태를 수집 실패와 혼동하지 않는다
    And 플랫폼의 설치 환경을 관측 대상의 실행 환경으로 추정하지 않는다

  Scenario: BDD-INF-005 ECS 실행을 task 식별과 당시 빌드 근거에 연결한다
    Given 합성 ECS service의 교체 전후 task 참조와 task definition revision 및 실제 이미지와 빌드 연결 근거가 있다
    And Fargate task에 대해 사용자가 조회할 수 있는 호스트 자산 근거는 없다
    When 에이전트가 교체 전후의 요청 실행과 인프라 문맥을 조회한다
    Then 요청은 당시 task와 해당 빌드 및 배포 근거에 연결되고 교체 전후 이력을 구분한다
    And Pod 관계나 임의의 EC2 호스트를 생성하지 않고 호스트 가시성의 지원 한계를 설명한다
    And task definition revision만으로 코드 버전을 확정하지 않는다

  Scenario: BDD-INF-006 EKS와 일반 Kubernetes의 같은 이름을 구분한다
    Given AWS EKS와 온프레미스 Kubernetes에 같은 namespace와 이름의 워크로드가 있다
    And 각 객체의 클러스터 식별과 UID 및 수집 출처가 기록되어 있다
    When 에이전트가 각 서비스 실행의 워크로드와 자원 관계를 조회한다
    Then 해당 클러스터와 UID 및 시점에 맞는 관계를 각각 반환한다
    And 일반 Kubernetes에 AWS 계정이나 ARN을 필수로 요구하지 않는다
    And AWS 연결 근거가 없다는 이유로 Kubernetes 관계를 미수집으로 표시하지 않는다
