# 원본 재확인·변경 알림 실험실

웹훅과 스케줄러가 같은 durable 작업을 요청하고, worker가 실제 원본 버전을 확인한 뒤 파일·blob 관계를 게시한다. 설치된 Git과 Python 표준 라이브러리만 사용한다. 임시 합성 게시판 저장소·loopback 수신·단일 머신 SQLite를 사용하며 외부 인프라를 만들지 않는다.

저장소 루트에서 실행한다.

```sh
python3 -m unittest experiments.reconciliation_lab.test_reconciliation -v
python3 -m experiments.reconciliation_lab.run --repetitions 3
```

이전 합성 실험의 회귀 검증도 함께 실행한다.

```sh
python3 -m unittest discover -s experiments/architecture_lab -p 'test_*.py' -v
python3 -m experiments.architecture_lab.lab --output results/architecture-lab --changes 200
```

실제 공개 GitHub 레포의 읽기 smoke를 포함하려면 다음 명령을 사용한다. GET만 수행하며 webhook 등록이나 외부 쓰기는 없다. 토큰은 선택적인 `JJAMTONG_GITHUB_TOKEN` 환경변수로만 읽고 결과에 쓰지 않는다. 비공개 저장소·다른 계정·사내 GitHub는 이번 대상이 아니다.

```sh
python3 -m experiments.reconciliation_lab.run --repetitions 3 --live-github
```

대상은 `DDINGJOO/JJAM-TONG`의 공개 `main`과 `experiments/` 파일 메타데이터다. live smoke는 정상·조건부 조회, 존재하지 않는 ref의 실제 HTTP 실패, 재시도 대기 후 정상 ref 회복을 확인한다. API 장애나 실제 GitHub 발 webhook을 시험하지 않는다. API 제한에 걸리면 반복하지 않고 실패를 보고한다.

## 구성

| 파일 | 책임 |
| --- | --- |
| [adapters.py](adapters.py) | immutable commit/tree 조회, 변경 없는 버전 생략, ETag·HTTP 실패·완전한 tree 확인 |
| [reconcile.py](reconcile.py) | durable receipt·작업 병합·lease token·원자적 게시·캐시·연결 회수 |
| [receiver.py](receiver.py) | loopback HTTP 수신, HMAC·대상·크기 검증, 저장 뒤 ACK |
| [worker.py](worker.py) | 같은 계약을 쓰는 유한 one-shot 별도 프로세스 |
| [fixtures.py](fixtures.py) | 고정 시각·합성 작성자의 실제 Git 커밋과 독립 blob 기대값 |
| [test_reconciliation.py](test_reconciliation.py) | H01~H14 정상·장애·복구 계약 |
| [run.py](run.py) | poll/hints/hybrid × 두 실행 경계 × 반복 실행·결과 생성 |

Python 3.9 이상을 대상으로 작성했다. 실제 버전·OS·Git·SQLite는 결과에 기록한다. `-O` 모드는 비교 runner의 판정을 없애므로 거절한다. Git 2.28 이상의 `init -b`를 사용한다. 현재 fixture는 SHA-1 Git 저장소와 POSIX 개발 환경에서 검증했다.

## 결과와 한계

- [설계·판정·자원 예산](../../docs/experiments/HYBRID-RECONCILIATION.md)
- [공개 실행 결과](../../docs/experiments/HYBRID-RESULTS.md)
- [입력 hash·환경·관측값](../../docs/experiments/hybrid-snapshot.json)
- [비교 축·기존 실험](../../docs/experiments/ARCHITECTURE-EXPERIMENTS.md)

인덱스는 포함 경로의 일반 파일·blob ID다. symlink·submodule은 따라가지 않고 Java 호출 분석·빌드·trace는 생성하지 않는다. 원본 코드 본문은 보고서에 싣지 않는다. 수신 본문은 hash와 delivery 식별자만 보존하며 영구 이벤트 원장이 아니다. 공개 fixture HMAC key는 실험용 표시값으로 운영 인증값이 아니다.

별도 worker는 같은 머신의 SQLite 파일을 공유한다. lease 기본값 30초, 작업 도중 갱신 없음, 원본 요청당 timeout 10초다. 30초 안에 끝나지 않으면 게시가 거절되고 lease 만료 후 재처리한다. 처리된 receipt의 보존 정책·디스크 총량·상시 worker·분산 broker·다중 머신 운영·실제 공급원 권한 회수·query ACL은 후속이다. 이 실험의 연결 회수는 수집 중단이며 보존 자료의 조회 허용 정책을 구현한 것이 아니다.

원본 중단 시 알림이 도착해도 재조회형 갱신은 실패한다. 현재 상태 확인과 이력 수집을 구분하며, 중간 커밋이나 짧은 실행 이력을 복원했다고 표현하지 않는다. 전체 BDD 47개와 AWS/EKS/ECS·CMDB·SIEM 지원은 별도 검증 대상이다.
