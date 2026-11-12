# 로드맵과 기록 규칙

[위키 홈](Home.md) · 원본: [로드맵](../../ROADMAP.md), [기여 가이드](../../CONTRIBUTING.md), [프로젝트 정의](../PROJECT.md)

## 작업을 찾는 곳

[프로젝트 #1](https://github.com/DDINGJOO/JJAM-TONG/issues/1)에서 부모·자식 이슈를 따라가고, [전체 로드맵](../../ROADMAP.md)에서 에픽·스토리·태스크와 선행 조건을 확인한다. milestone은 목표 구간이며 확정 출시일을 뜻하지 않는다.

| 보고 싶은 것 | 바로가기 |
| --- | --- |
| 에픽·스토리 | [에픽](https://github.com/DDINGJOO/JJAM-TONG/issues?q=is%3Aopen+label%3A%22kind%3Aepic%22), [스토리](https://github.com/DDINGJOO/JJAM-TONG/issues?q=is%3Aopen+label%3A%22kind%3Astory%22) |
| 현재 착수·검토 | [진행 중](https://github.com/DDINGJOO/JJAM-TONG/issues?q=is%3Aopen+label%3A%22status%3Ain-progress%22), [검토 중](https://github.com/DDINGJOO/JJAM-TONG/issues?q=is%3Aopen+label%3A%22status%3Ain-review%22) |
| 다음 작업·차단 | [착수 가능](https://github.com/DDINGJOO/JJAM-TONG/issues?q=is%3Aopen+label%3A%22status%3Aready%22), [백로그](https://github.com/DDINGJOO/JJAM-TONG/issues?q=is%3Aopen+label%3A%22status%3Abacklog%22), [막힘](https://github.com/DDINGJOO/JJAM-TONG/issues?q=is%3Aopen+label%3A%22status%3Ablocked%22) |
| 완료·변경 기록 | [닫힌 이슈](https://github.com/DDINGJOO/JJAM-TONG/issues?q=is%3Aissue+is%3Aclosed), [PR](https://github.com/DDINGJOO/JJAM-TONG/pulls?q=is%3Apr), [milestone](https://github.com/DDINGJOO/JJAM-TONG/milestones) |

위키에는 진행 상태나 완료율을 다시 적지 않는다. 실제 상태는 GitHub open/closed·단일 `status:*` 라벨·Parent/Sub-issues·milestone이 기준이다. 개인 진행 leaf 태스크는 한 번에 하나다.

## 어떤 이야기를 어디에 남기는가

| 기록할 내용 | 원본 위치 | 연결할 근거 |
| --- | --- | --- |
| 목적·전체 범위·사용자 결과 | [VISION](../VISION.md), [PROJECT](../PROJECT.md) | 요구사항 에픽·스토리 |
| 행동·반례·지원 차이 | [BDD 인덱스](../requirements/README.md), feature | 시나리오 ID·검토/검증 태스크 |
| 설계 질문·대안·장단점 | [DISCUSSIONS](../DISCUSSIONS.md) | 관련 요구사항·판별 실험 이슈 |
| OSS 조사·버전·라이선스 | [RESEARCH](../RESEARCH.md), [OSS 비교](../OSS-ARCHITECTURE-COMPARISON.md) | 공식 원문·조사 시점·미확인 조건 |
| 선택·보류·변경 이유 | `docs/decisions/`의 [ADR](../decisions/0001-reconciliation-baseline.md) | 대안·검증·연결 이슈·이전 결정 |
| 실행·실패·실측·한계 | `docs/experiments/`의 [결과](../experiments/HYBRID-RESULTS.md) | 입력·코드 버전·환경·명령·판정 |
| 해야 할 일·진행 상태·완료 증거 | [Issues](https://github.com/DDINGJOO/JJAM-TONG/issues), PR | 부모·자식·milestone·시나리오·문서·commit |

## 갱신과 완료

논의로 요구나 선택이 바뀌면 해당 원본 문서를 수정하고, 같은 PR에서 영향받는 위키 페이지의 요약·링크를 맞춘다. 이슈·PR에 시나리오·토론·ADR·검증 결과를 연결한다. 과거 결정·실패 기록은 삭제해 새 결론처럼 보이게 하지 않는다.

문서 변경은 링크·원본 대응·공개 발행을 확인한다. 코드 변경은 관련 검증을 수행하고 미실행 범위를 적는다. 완료 조건과 근거를 확인한 태스크만 닫으며 부모의 완료는 별도 판정한다. 새 의존성은 소유자의 명시적 선택과 ADR 뒤 채택한다.

위키 원본 관리와 GitHub Wiki 발행 절차는 [관리 안내](README.md)에 있다. 실제 소스 비밀·payload·개인정보·토큰·보안 이벤트를 공개 기록에 넣지 않는다.
