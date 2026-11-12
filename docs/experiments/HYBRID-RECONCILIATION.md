# 원본 재확인과 변경 알림의 통합 실험

상태: **제한된 실험 구현·실행 검증 / 2026-11-12**. 연결 이슈: [T20 #36](https://github.com/DDINGJOO/JJAM-TONG/issues/36), 상위 [S10 #34](https://github.com/DDINGJOO/JJAM-TONG/issues/34). [실행 결과](HYBRID-RESULTS.md) · [환경·입력 hash·관측값](hybrid-snapshot.json).

사용자가 2026-11-12 논의에서 주기적 재확인과 변경 알림을 결합하는 안의 검증 진행을 승인했다. 이를 관계 갱신의 실험 기본안으로 사용한다. 제품 언어·저장소·메시지 브로커·클라우드 설치 환경은 이번 실험으로 결정하지 않는다.

## 가설과 대안

웹훅과 스케줄러가 같은 원본 재확인 작업을 요청하면 알림의 역순·중복에 영향받지 않고 확인 가능한 현재 상태로 수렴할 수 있다. 원본 버전이 같으면 관계 재생성을 생략할 수 있다. 별도 worker는 수신과 작업 실패 경계를 나눌 수 있지만 프로세스·lease·재시도·상한 관리가 추가된다.

반대 가설도 확인한다. 웹훅만으로 충분하거나 폴링만으로 지연 예산을 만족하면 혼합 경로의 운영 부담이 이득보다 클 수 있다. 원본 중단 중에는 재확인형 이벤트 처리도 진행되지 않는다. 앞선 합성 실험의 payload 직접 반영 방식과 이 점이 다르다. 현재 상태로 수렴해도 관측하지 못한 중간 커밋·실행 이력을 모두 수집했다는 뜻은 아니다.

## 데이터별 수집 계약

| 영역 | 검증 기본안 | 이번 실행 범위 |
| --- | --- | --- |
| Git·코드·카탈로그 | 알림으로 확인을 앞당기고 주기적으로 버전 재확인; 변경 범위를 계산 | 실제 임시 Git 저장소, GitHub REST 공개 레포 조회, 파일·blob 관계 인덱스 |
| Kubernetes | 최초 list와 watch, 이어받을 수 없을 때 relist | 문서상 계약, 실제 클러스터 미실행 |
| AWS·온프레미스 자산 | API 조회와 공급원별 변경 알림 조합 | 공급원·권한·주기별 후속 검증 |
| trace·감사·보안 사건 | 원본 이벤트 수집·보존·재시도와 공백 표시 | 앞선 합성 실험의 이력 한계 유지; 실제 수집 미실행 |

GitHub REST는 웹훅 활용을 우선 권고하고, 폴링 시 필요한 주기·조건부 요청·호출 제한을 지키도록 안내한다. 따라서 원본마다 고정된 짧은 전체 조회를 강제하지 않는다. [REST 권고](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api).

Kubernetes watch는 보존된 resourceVersion 이후 변경을 추적하며 오래된 버전으로 재개할 수 없을 때 재조회가 필요하다. 이는 영구 감사 원장과 다르다. [Kubernetes API](https://kubernetes.io/docs/reference/using-api/api-concepts/#efficient-detection-of-changes).

## 통제 조건과 구현 경계

Python 표준 라이브러리·SQLite·설치된 Git만 사용한다. Python·Git·SQLite 실제 버전은 실행 결과에 기록한다. 새 패키지나 OSS 서버를 설치하지 않는다. Python/SQLite/Git의 시스템 설치를 사용하며 소스를 번들·재배포하지 않는다. GitHub REST는 API 버전을 명시한다. 별도 플랫폼 라이선스와 운영용 의존성 채택은 미결이다.

| 실험 도구·접근 | 라이선스·권한·설치 조건 |
| --- | --- |
| Python 3.9+ 표준 라이브러리 | 기존 시스템 설치, [PSF license](https://docs.python.org/3/license.html) |
| SQLite | Python 내장 모듈과 기존 라이브러리, [public domain](https://www.sqlite.org/copyright.html) |
| Git 2.28+ | 기존 CLI, [GPLv2](https://git-scm.com/about/free-and-open-source); 소스를 배포하지 않고 subprocess로 실행 |
| 공개 GitHub REST | API `2026-03-10`, 공개 데이터 GET은 무인증 가능; 인증 시 해당 저장소 Contents read 범위, 실험은 개인 계정의 기존 인증 사용 |
| loopback 웹훅 | 합성 payload와 공개 표시 key, 외부 수신·App 설치·webhook 관리 권한 없음 |

- 같은 Git 커밋 순서, SQLite 계약, 포함 경로, 분석기/스키마/설정 버전, 이벤트·조회 일정으로 in-process와 one-shot 별도 worker를 비교한다.
- 임시 Git 원본에는 합성 커뮤니티 게시판 Java 파일만 만든다. Git subprocess는 인수 배열로 실행하고 원본 코드를 실행하지 않는다.
- 분석은 파일 경로와 blob ID의 버전별 관계 인덱스다. Java 메서드 호출 분석·런타임 추적·실제 빌드 식별은 구현하지 않는다. commit을 build/artifact로 간주하지 않는다.
- 웹훅은 대상 저장소·ref의 변경 힌트다. HMAC·크기·event type·delivery ID를 검증하고, 수신을 durable inbox에 커밋한 뒤 성공 응답한다. 본문의 `after`를 현재 상태로 직접 게시하지 않는다.
- 스케줄러와 수신기는 source별 하나의 보류 작업을 공유한다. 작업 중 들어온 요청은 다음 실행 대상으로 남긴다. 처리되지 않은 수신 건수에 상한을 두고 초과분은 거절해 조용히 유실시키지 않는다.
- worker는 lease token으로 소스당 동시 게시를 직렬화한다. lease가 만료되거나 연결이 회수된 이전 작업은 결과를 게시하지 못한다. 원본 읽기는 DB transaction 밖에서 수행한다.
- Git은 ref를 한 번 해석한 immutable commit/tree를 읽는다. GitHub는 commit 확인과 해당 tree 조회를 분리하며 `truncated` 응답을 부분 성공으로 게시하지 않는다.
- 최신 버전 표시·snapshot·inbox 처리 완료·조건부 요청 캐시는 같은 transaction에 반영한다. 실패 시 마지막 성공 결과와 새 오류를 함께 보존한다.
- 커밋 hash를 정렬해 최신을 추정하지 않는다. 실제 ref 되돌림도 기록하며 관측 순서와 원본 버전을 구분한다. 포함 경로나 분석기 설정이 달라지면 같은 commit도 별도 분석 결과다.
- 로컬 수신기는 loopback에만 바인딩한다. GitHub App 설치·외부 공개 endpoint·실제 웹훅 등록·AWS/Kubernetes 변경 권한은 사용하지 않는다.

## 기대값과 실패 실험

| ID | 시나리오 | 독립 판정 |
| --- | --- | --- |
| H01 | 최초 원본 조회 | 예상 파일·blob·commit의 비어 있지 않은 인덱스 |
| H02 | 변경 없는 주기 확인 | 원본 확인은 증가, 분석 횟수·snapshot 수 불변 |
| H03 | 변경 알림 | payload 대신 원본 commit의 결과 게시 |
| H04 | 알림 유실 | 다음 주기 재확인 뒤 현재 commit으로 수렴 |
| H05 | 중복·역순 알림 | 중복 작업 제한, 오래된 알림으로 결과 역행하지 않음 |
| H06 | 추가·이름 변경·삭제 | 새 snapshot의 정확한 경로 집합, 이전 snapshot 보존 |
| H07 | 원본 중단·부분 응답 | 성공 시점·최신 결과·cache를 바꾸지 않고 오류 표시; 재시도 후 복구 |
| H08 | 수신 뒤/게시 transaction 도중 프로세스 종료 | 재시작·lease 만료 후 재처리, 잘못된 성공 없음 |
| H09 | 두 worker·오래된 lease | 새 소유자만 게시; 이전 token 결과 거절 |
| H10 | 연결 회수 | 예약·보류·진행 중 작업의 새 게시 중단 |
| H11 | 폭주·상한 | 보류 작업 병합, inbox 상한 초과 요청은 거절; 성공 응답 건은 보존 |
| H12 | 서명·대상·payload 크기 오류 | 작업·원본 조회·snapshot에 영향 없음 |
| H13 | commit 되돌림·설정 변경 | hash 정렬 없이 실제 ref 반영; 다른 분석 설정 결과 분리 |
| H14 | 원본 검증과 캐시 | HTTP 조건부 요청·304, 실패 후 회복, 완전한 tree만 게시 |

앞선 X01~X16은 그대로 회귀 실행한다. H01~H14는 Git 갱신 경로의 새 검증이며 CMDB·SIEM·query ACL·build 연결의 모든 기대값을 실제 GitHub에 이식한 것으로 집계하지 않는다.

## 측정과 자원 예산

두 실행 경계에 같은 fixture를 여러 차례 반복하고 원본 확인 수·실제 인덱스 생성 수·snapshot 수·거절 수·복구 결과·경과 시간을 기록한다. 별도 worker 시간에는 프로세스 시작 비용이 포함된다. 단일 개발 머신의 one-shot worker 비교이며 상시 worker 처리량·운영 성능·클라우드 비용으로 일반화하지 않는다.

비교 일정의 `0, 1, 2, 5, 10, 12, 15, 20`은 주입한 논리 시각이다. 정상 초기화, 즉시 변경, 오래된 알림, 주기 수렴, 알림 유실 후 주기, 묶인 변경, 최종 현재 상태, 변경 없는 확인의 8개 체크포인트를 쓴다. 이는 실제 갱신 지연의 초 단위 측정이 아니다. 같은 지연을 여러 체크포인트에서 확인하므로 미달 개수를 독립 장애 건수로 세지 않는다. 경과 시간만 실제 wall clock의 단일 머신 일정 실행 시간이다.

로컬 실험은 loopback·임시 디렉터리·프로세스당 작업 한 건·유한 시나리오로 끝낸다. 실제 GitHub 확인은 `DDINGJOO/JJAM-TONG` 공개 메타데이터에 제한된 GET만 사용한다. 공개 실행 산출물에는 인증값·사용자 홈 경로·실제 source 본문을 넣지 않는다. 403/429·Retry-After는 지연 재시도를 예약하며 즉시 반복하지 않는다.

수집 회수는 이 실험의 connection switch로 확인한다. 실제 GitHub App 권한 회수·필드/관계 조회 인가·다중 tenant·다중 머신·네트워크 분할·TLS 공개 수신·영구 이력 완전성은 후속 검증이다. 실측·주입 장애·미실행을 결과에서 구분한다.

## 공식 근거

- [Argo CD FAQ](https://argo-cd.readthedocs.io/en/stable/faq/#how-often-does-argo-cd-check-for-changes-to-my-git-or-helm-repository): 폴링과 웹훅을 조합할 수 있고 알림 실패를 고려한다.
- [GitHub 웹훅 권고](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks): 서명 검증·빠른 응답·비동기 처리·delivery 식별자.
- [실패 웹훅 재전송](https://docs.github.com/en/webhooks/testing-and-troubleshooting-webhooks/redelivering-webhooks): 실패 건 자동 재전송 없음.
- [GitHub commit 조회](https://docs.github.com/en/rest/commits/commits#get-a-commit), [tree 조회](https://docs.github.com/en/rest/git/trees#get-a-tree): 원본 버전과 tree 참조, 읽기 권한, truncated 조건.

확인일: 2026-11-12. 테스트 17개·기존 회귀 테스트 9개, 두 실행 경계 × 세 갱신 전략 × 세 반복의 18회 비교를 수행했다. 144개 체크포인트 중 목표 미달 24개를 숨기지 않고 결과에 남겼다. 실제 공개 REST는 최초 조회·조건부 304·잘못된 ref 422·회복을 확인했다. 파일 인덱스 이후의 실제 공급원 정책·상시 worker는 [T21 #37](https://github.com/DDINGJOO/JJAM-TONG/issues/37), 보관·조회·실제 메서드 분석 비교 조건은 [T22 #38](https://github.com/DDINGJOO/JJAM-TONG/issues/38)로 이어간다.
