# 원본 재확인·변경 알림 실행 결과

실행일: 2026-11-12T02:45:07.864753+00:00

[설계·범위](HYBRID-RECONCILIATION.md) · [실험실](../../experiments/reconciliation_lab/README.md) · [환경·입력 hash·반복 관측값](hybrid-snapshot.json)

실제 임시 Git 원본과 loopback HTTP 수신기를 사용했다. 모든 방식은 같은 포함 경로·파일 인덱스·SQLite 계약을 쓴다. `hints`는 payload 직접 반영이 아니라 원본 재조회를 요청하는 알림 전용 방식이다.

## 같은 일정의 반복 비교

| 실행 경계 | 갱신 전략 | 반복 | 확인/인덱스 생성¹ | 목표 미달¹ | 경과 중앙값(초)² |
| --- | --- | --- | --- | --- | --- |
| in_process | poll | 3 | 5/4 | 3 | 0.2341 |
| in_process | hints | 3 | 4/3 | 1 | 0.2142 |
| in_process | hybrid | 3 | 8/4 | 0 | 0.2579 |
| subprocess | poll | 3 | 5/4 | 3 | 0.5558 |
| subprocess | hints | 3 | 4/3 | 1 | 0.5306 |
| subprocess | hybrid | 3 | 8/4 | 0 | 0.5825 |

¹ 한 실행의 수치이며 목표 미달의 분모는 8개 체크포인트다. 같은 변경의 주기 전 지연을 여러 체크포인트에서 볼 수 있어 독립 장애 건수나 성공률로 환산하지 않는다. ² 해당 머신의 fixture 일정 실행 시간으로 원본 Git 명령·HTTP 왕복을 포함한다. subprocess에는 매 작업의 Python 프로세스 시작 비용이 포함된다. 상시 worker의 처리량·갱신 SLO·우위로 해석하지 않는다.

- 즉시 변경은 poll에서 다음 주기까지 지연됐다. hints/hybrid는 수신 뒤 원본을 확인했다.
- 알림이 없는 변경은 poll/hybrid에서 다음 주기에 확인됐고 hints에는 누락됐다.
- 중복·오래된 알림으로 원본이 가리키는 현재 commit을 덮어쓰지 않았다.
- 변경 없는 확인에서는 파일 인덱스 재생성을 건너뛰었다.
- 두 번의 변경을 묶어 처리하면 세 방식 모두 중간 commit의 인덱스를 만들지 못했다. 이벤트 원장이나 모든 커밋 수집의 검증이 아니다.
- 두 실행 경계의 의미상 결과가 일치했다. 단일 머신 SQLite를 공유하므로 다중 머신·broker 장애 격리를 검증하지 않았다.

## 실제 공개 GitHub 읽기

대상: `DDINGJOO/JJAM-TONG` / `main` / `b2f5849496bef893a4d355d7f0e50ff1283d1a80`. API `2026-03-10`. 포함 경로 `experiments/`에서 파일 5개를 확인했다.

| 단계 | 실제 결과 |
| --- | --- |
| initial_read | published |
| conditional_recheck | published |
| actual_missing_ref | http_422 |
| actual_source_recovered | published |

원본 호출 관측: `{"checks": 4, "http": 5, "not_modified": 2, "trees": 1}`. 실제 실패는 존재하지 않는 ref의 조회이며 GitHub 서비스 장애를 유발하지 않았다. 실제 GitHub 발 웹훅·App 설치·권한 회수는 실행하지 않았다.

## 판정과 남은 범위

별도 unittest는 H01~H14의 정상·실패 계약을 확인한다. 실제 자식 프로세스 종료 두 지점·동시 worker·lease fencing·연결 회수·설정 변경·backpressure·조건부 HTTP·부분 tree·429 Retry-After를 포함한다. 429와 부분 tree는 loopback 주입이고 연결 회수는 로컬 switch다.

앞선 X01~X16·48회 합성 실험의 결과는 별도로 유지한다. 현재 구현은 Git 파일·blob 관계이며 메서드 호출 그래프·빌드/trace 결합·클러스터·AWS·CMDB·SIEM·다중 tenant/query ACL·전체 BDD 수락은 미실행이다. 처리된 inbox 보존 기간·디스크 상한·lease 갱신·영구 실패 격리·상시 worker 운영도 후속이다.
