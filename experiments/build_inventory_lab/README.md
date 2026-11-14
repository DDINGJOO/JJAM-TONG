# 빌드 명세와 기준선 비교 실험

작은 합성 fixture로 해시 불일치, 기준선 선택, 부분 근거, 과거 기록 보존을 검사한다. 비교 경로와 기대값이 독립적인 단위 시험은 `tools/build_inventory/test_baseline.py`에 있다. 원본 파일은 임시 디렉터리에 만들며 대상 앱을 실행하지 않는다.

```sh
python3 -m experiments.build_inventory_lab.run --output /absolute/output/synthetic-run.json
```

별도 공개 Playground에 보존된 두 산출물·원본 명세·분석 색인을 지정하면 정확한 연결도 확인한다. 다음 경로는 각자의 로컬 위치로 바꾼다. 출력은 새 파일이어야 한다.

```sh
python3 -m experiments.build_inventory_lab.run \
  --public-target /absolute/JJAM-TONG-playground \
  --public-evidence-root /absolute/retained \
  --baseline-metadata /absolute/retained/b1/build-manifest.json \
  --current-metadata /absolute/retained/b2/build-manifest.json \
  --baseline-index /absolute/retained/b1/index.json \
  --current-index /absolute/retained/b2/index.json \
  --output /absolute/output/public-run.json
```

공개 리포트용 대상은 `DDINGJOO/JJAM-TONG-playground`로 제한한다. 해당 저장소의 기록된 입력 해시와 현재 읽을 수 있는 파일을 대조하고, 선택한 산출물과 기존 분석의 다섯 빌드 필드를 일치시킨다. 없는 classpath·도구체인·생성 소스·빌드 조건은 `unavailable`로 남긴다. 동일 소스의 재빌드에서 JAR이 달라도 이를 소스 변경이나 실행 회귀라고 해석하지 않는다.

이 실험의 명세와 검사 시각은 이번 실행 시각이다. 과거 당시 수집했다는 증명이나 소스→JAR의 신뢰 가능한 출처, 새로운 Java 분석·요청 Trace가 아니다. 공개 대상의 Git 상태를 읽기 전후에 대조하고, 빌드·DB 쓰기·대상 코드 변경을 수행하지 않는다.

비공개 저장소는 일반 발견 CLI로 로컬에서만 확인하며, 이름·경로·통계·결과를 공개 리포트에 넣지 않는다. [계약](../../docs/requirements/BUILD-INVENTORY.md)·[결과](../../docs/experiments/BUILD-INVENTORY-RESULTS.md)에서 지원 범위와 후속 검증을 확인한다.

공개용 명세·분석 파일은 명시한 `--public-evidence-root` 아래에 두어야 한다. 심볼릭 링크·루트 밖 경로·중복 JSON 키와 10 MiB 초과 입력을 거부한다. Git 조회는 출력 1 MiB와 20초를 상한으로 두며, 공개 리포트에는 Git 상태의 해시만 남긴다.
