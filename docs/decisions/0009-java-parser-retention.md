# ADR 0009 Java 파서의 소스 위치 보존과 조회 캐시 정책

- 상태: 한정된 로컬 분석 도구에 적용. 플랫폼 전체의 자원 정책·스택 채택은 미결이다.
- 날짜: 2026-11-14
- 작업: [#63](https://github.com/DDINGJOO/JJAM-TONG/issues/63), 상위 [#44](https://github.com/DDINGJOO/JJAM-TONG/issues/44)
- 선행: [ADR 0008](0008-exact-input-analysis-reuse.md)

## 문제와 확인한 근거

기존 어댑터 0.2.0은 301,231줄 합성 입력에서 JavaParser의 소스 파싱 중 힙을 초과했다. WALA의 클래스 계층 분석에 진입하기 전의 실패였다. 소스 위치를 추출하는 파서 설정을 타입 조회용 `JavaParserTypeSolver`에도 공유하고 있었다.

이전 구현을 다시 빌드해 같은 1 GiB 힙에서 실패를 재현했다. 조회 캐시의 항목 수만 제한한 실험도 실패했다. 모든 파서의 토큰 보관을 끄면 분석이 완료됐으나 선언·호출의 줄 번호가 사라졌다. 토큰은 파서가 보관하는 소스의 어휘 단위다. 단순히 완료됐다는 이유로 위치 정보가 빠진 결과를 채택하지 않는다.

## 결정과 대안

| 대안 | 결과와 선택 |
| --- | --- |
| 기존 설정 유지 | 30만 줄 입력이 기존 힙에서 실패했다. 비교 기준으로 보존한다 |
| 조회 캐시만 제한 | 같은 입력에서 힙 실패가 남았다 |
| 모든 파서의 토큰 보관 해제 | 분석은 완료됐으나 소스 줄 번호를 잃어 제외했다 |
| 소스 파서와 타입 조회 파서의 보관 설정 분리 | 위치·관계 대조를 통과해 로컬 도구에 적용한다 |
| 힙 상향 | 이전 결과를 얻는 진단용 기준에만 사용했다. 현재 CLI의 제한은 변경하지 않는다 |

직접 소스를 읽는 파서는 토큰과 소스 위치를 유지한다. 타입 조회용 파서는 토큰·주석 보관을 끄고 조회 캐시의 항목 수를 제한한다. 두 설정은 같은 언어 수준, 전체 타입 해석기와 심볼 해석기를 사용한다. 패키지·프로젝트명·폴더 깊이에 따른 분기는 추가하지 않는다.

고정 버전 JavaParser 3.28.2의 생성자에 `32`를 전달한다. 이 값은 조회 캐시의 항목 수 제한이며 전체 구문 트리(AST)의 개수·크기나 힙·프로세스 메모리의 상한이 아니다. 다른 타입 해석기와 WALA의 보유 메모리까지 제한하지 않는다. 32개가 모든 프로젝트에 최적인지는 아직 검증하지 않았고, 캐시 축소로 재파싱 비용이 늘 수 있다. 두 파서에 향후 문법 설정을 추가할 때는 언어·해석 조건이 달라지지 않도록 함께 검토한다.

분석기 버전은 `0.2.0`에서 `0.2.1`로 올린다. 기존 재사용 키의 JAR 해시가 바뀌고 소비자 색인의 분석 설정 해시도 바뀌므로, 이전 분석을 새 정책의 결과로 재사용하지 않는다. 근거 스키마와 정적 후보의 의미는 유지한다. 새 의존성은 추가하지 않는다.

## 검증과 후속

[실측 결과](../experiments/JAVA-PARSER-MEMORY.md)에서 10만·30만 줄의 최초·재사용·변경·독립 전체 분석을 대조한다. 이전 분석기의 2 GiB 실행은 30만 줄 결과의 정확성 기준이며 같은 예산의 비용 비교가 아니다. 전체 본문을 대조할 때 빌드 메타데이터와 그 해시, 의도적으로 바뀐 분석기 버전만 제외하고 소스 위치·관계·미해결 이유는 그대로 비교했다.

캐시 크기 변화의 보유 메모리 비중은 힙 덤프로 분해하지 않았다. 여러 프로젝트의 의존성·다형성·호출 밀도와 동시 실행 수에 대한 수용량도 아직 검증하지 않았다. 단계별 발행·출력 분할과 공통 자원 계약은 [#64](https://github.com/DDINGJOO/JJAM-TONG/issues/64), 빌드·모듈의 변경 영향은 [#65](https://github.com/DDINGJOO/JJAM-TONG/issues/65), 프레임워크·HTTP·이벤트 근거는 [#66](https://github.com/DDINGJOO/JJAM-TONG/issues/66)으로 이어간다.

## 고정 버전의 공식 근거

JavaParser 3.28.2의 [타입 조회 생성자와 캐시 제한](https://javadoc.io/static/com.github.javaparser/javaparser-symbol-solver-core/3.28.2/com/github/javaparser/symbolsolver/resolution/typesolvers/JavaParserTypeSolver.html), [해당 릴리스 소스](https://github.com/javaparser/javaparser/blob/javaparser-parent-3.28.2/javaparser-symbol-solver-core/src/main/java/com/github/javaparser/symbolsolver/resolution/typesolvers/JavaParserTypeSolver.java), [파서 설정 API](https://www.javadoc.io/static/com.github.javaparser/javaparser-core/3.28.2/com/github/javaparser/ParserConfiguration.html)를 확인했다. API 제공 여부와 실제 비용·위치 보존의 검증을 구분한다.
