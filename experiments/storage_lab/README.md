# 버전 근거 저장소 비교 실험

PostgreSQL·Neo4j·Elasticsearch·ClickHouse에 같은 합성 근거를 넣고, 버전별 관계 조회·로그 검색·집계와 장애 복구를 비교한다. 제품 DB 채택이나 운영 지원 범위의 확정을 뜻하지 않는다. [결과와 설계 검토](../../docs/experiments/STORAGE-ENGINE-COMPARISON.md)에 수치·공식 근거·앞으로 검증할 항목을 기록한다.

## 실행

저장소 루트에서 실행한다. Docker Compose, Python 3.9 이상과 실험용 Psycopg가 필요하다. 네 종류의 서버와 드라이버는 이번 비교에만 추가했다. 제품 라이브러리의 의존성은 바꾸지 않는다.

```sh
python3 -m venv .local/storage-lab/venv
.local/storage-lab/venv/bin/pip install -r experiments/storage_lab/requirements.txt
.local/storage-lab/venv/bin/python -m unittest discover -s experiments/storage_lab -t . -v
docker compose -f experiments/storage_lab/compose.yaml config --quiet
.local/storage-lab/venv/bin/python -m experiments.storage_lab.run --repetitions 20
.local/storage-lab/venv/bin/python -m experiments.storage_lab.federation
.local/storage-lab/venv/bin/python -m experiments.storage_lab.report
```

전체 실행은 전용 이름 `jjamtong-storage-lab`의 컨테이너와 볼륨만 사용한다. 다른 실습의 DB·Kubernetes·서비스는 중단하거나 변경하지 않는다. 기존 DB 데이터가 있더라도 이 실험의 `evidence` 테이블·색인은 다시 만든다. 같은 실험을 동시에 두 번 실행하지 않는다.

서버는 loopback 주소의 29432·29474·29420·29423 포트를 사용한다. 합성 데이터만 넣는 로컬 구성으로, Neo4j·Elasticsearch 인증은 끈 상태다. tenant 조건 검증을 기업 인증·권한 격리 시험으로 해석하지 않는다.

빠른 기능 확인에는 다음 명령을 쓴다. 작은 입력만 사용하는 결과이므로 전체 비교의 결과 파일과 분리한다.

```sh
.local/storage-lab/venv/bin/python -m experiments.storage_lab.run \
  --quick --repetitions 5 --output results/storage-lab-smoke
```

## 구현과 판정

- `fixtures.py`: 두 tenant·두 빌드·서로 다른 분석 설정, 정적 후보·실행 span·인프라·로그를 만든다. 같은 commit의 두 빌드에는 다른 합성 artifact 해시를 준다. 실제 Java 분석 결과를 가져온 데이터는 아니다.
- `stores.py`: PostgreSQL 재귀 SQL, Neo4j 가변 길이 경로, Elasticsearch·ClickHouse의 깊이가 제한된 클라이언트 탐색을 비교한다. 검색은 합성 영문 메시지의 `timeout` 토큰으로 의미를 맞춘다.
- `run.py`: 독립 예상값, 단일 클라이언트 지연, 1·4·8개 클라이언트의 짧은 부하, 자원 표본·저장량, 실제 DB 중단·재시작을 실행한다.
- `pipeline.py`: PostgreSQL의 근거와 전송할 작업을 한 트랜잭션에 보관하는 outbox를 구현한다. 처리 완료 위치는 조회용 DB가 반영된 뒤 전진한다. 실제 자식 프로세스를 종료 코드 73으로 끊어 재처리를 검증한다.
- `federation.py`: PostgreSQL 원장·Neo4j 그래프·Elasticsearch 검색을 함께 조회한다. 한쪽 반영이 늦거나 artifact가 다르면 완전한 결합 결과를 반환하지 않는다.
- `report.py`: 원시 표본·입력 해시·이미지 digest·환경 요약을 공개용 JSON으로 묶는다.

outbox의 **at-least-once**는 같은 작업이 여러 번 전달될 수 있다는 뜻이다. 이 실험에서는 ID와 순서 번호로 중복·이전 버전의 재적용을 처리한다. 동일 근거의 같은 순서 번호에는 같은 내용이 와야 한다. 다중 작성자·다중 소비자 경합과 분산 트랜잭션은 구현하지 않았다.

## 결과·정리

원시 실행 결과는 Git 추적에서 제외한 `results/storage-lab/`에 남고, 공개용 사본은 [storage-engine-run.json](../../docs/experiments/storage-engine-run.json)에 있다. `first_measured_ms`는 이미 데이터를 적재하고 기능을 확인한 뒤의 값이며 차가운 디스크 조회가 아니다. Docker 메모리는 표본이며 최고 사용량을 보장하지 않는다.

실행 후 전용 컨테이너는 중단한다. 데이터 볼륨은 재현·검토를 위해 남긴다. 아래 명령은 전용 컨테이너·네트워크를 정리하며 볼륨을 삭제하지 않는다.

```sh
docker compose -f experiments/storage_lab/compose.yaml down
```
