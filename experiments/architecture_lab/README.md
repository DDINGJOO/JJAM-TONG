# 자동 갱신 아키텍처 실험실

동일한 입력·근거 계약·SQLite 저장소에서 `poll`, `events`, `hybrid`의 갱신 동작을 실행한다. Python 표준 라이브러리만 쓰며 외부 서비스·클라우드 자원·새 패키지가 필요하지 않다. Python/SQLite는 실험 도구이며 제품 구현 언어·스토리지의 채택 결정이 아니다.

저장소 루트에서 실행한다.

```sh
python3 -m unittest discover -s experiments/architecture_lab -p 'test_*.py' -v
python3 -m experiments.architecture_lab.lab --output results/architecture-lab --changes 200
```

Python 3.9 이상을 대상으로 작성했고 실제 확인 환경은 공개한 결과 JSON에 기록한다. `-O` 최적화 모드는 판정용 assertion을 비활성화하므로 실행을 거절한다. 결과 폴더는 git에서 제외하며 실행마다 JSON·Markdown을 만든다. 공개 실험 스냅샷은 [실험 결과](../../docs/experiments/RESULTS.md)에 있다.

- [실험 설계·방법론·다음 비교 축](../../docs/experiments/ARCHITECTURE-EXPERIMENTS.md)
- [합성 원본과 두 빌드](fixtures/base.json)
- [16개 시나리오·독립 기대값·BDD 연결](fixtures/scenarios.json)
- [구현](lab.py) · [장애·계약·판정 민감도 테스트](test_lab.py)

원본 API·정적 분석·실제 trace·CMDB·SIEM은 합성 입력이다. 이번에 실행한 범위는 갱신 전략·트랜잭션·제한된 조회 계약이며, 전체 BDD 47개 통과나 AWS/EKS/ECS 지원 완료를 의미하지 않는다.
