# 위키 원본과 발행

[공개 GitHub Wiki](https://github.com/DDINGJOO/JJAM-TONG/wiki)와 [저장소의 위키 홈](Home.md)에서 프로젝트 문서를 탐색한다. 이 디렉터리는 위키의 검토 가능한 원본이며 GitHub 저장소에서도 바로 읽을 수 있다. 본문 6개와 사이드바·푸터를 같은 원본에서 GitHub Wiki용으로 내보낸다. 상세 설계·BDD·실험 자료는 기존 경로에서 유지한다.

## 원본과 갱신 규칙

1. 비전·요구사항·토론·ADR·실험 결과는 해당 원본 문서를 수정한다.
2. 같은 PR에서 영향받는 위키 페이지의 요약·탐색 링크도 맞춘다. 상태는 복사하지 않고 이슈로 연결한다.
3. 문서 상대 링크와 위키 내보내기를 검증한 뒤 PR을 main에 반영한다.
4. GitHub Wiki에 발행할 때는 main의 원본을 내보내고 Wiki 저장소의 diff를 검토한 뒤 commit·push한다. PR 또는 작업 이슈에 원본 commit과 Wiki commit을 남긴다.

Wiki 웹 편집기로 본문을 별도 관리하면 두 원본이 갈라진다. 웹에서 수정했다면 저장소 원본에 변경을 먼저 반영한다. 내보내기 도구는 네트워크·로그인·push를 실행하지 않는다. 현재 자동 동기화 GitHub Actions는 구성하지 않았다.

## 로컬 검증·내보내기

저장소 루트에서 Python 표준 라이브러리만 사용한다.

```sh
python3 scripts/export_wiki.py
```

기본 출력 경로는 Git 추적에서 제외한 `.local/wiki-export/`다. 위키 페이지 사이의 상대 링크는 GitHub Wiki URL로, 기존 문서·명세 링크는 저장소 main URL로 변환한다. 관리 안내인 이 README는 Wiki 페이지로 복제하지 않는다. 검증한 파일 8개만 출력하고 다른 파일을 삭제하거나 Git에 반영하지 않는다.

## GitHub Wiki 초기화와 발행

GitHub Wiki는 별도 Git 저장소다. [공식 안내](https://docs.github.com/en/communities/documenting-your-project-with-wikis/adding-or-editing-wiki-pages)에 따라 소유자의 로그인된 브라우저에서 첫 페이지를 만든 뒤 clone할 수 있다. 기능 활성화와 첫 페이지 발행은 별개다. 이 초기화 및 공개 발행의 실제 결과는 [T23 #40](https://github.com/DDINGJOO/JJAM-TONG/issues/40)에 기록한다. 저장소의 위키형 허브는 이 단계와 독립적으로 읽을 수 있다.

초기화된 Wiki를 로컬에 clone한 뒤 다음처럼 내보낼 수 있다.

```sh
git clone https://github.com/DDINGJOO/JJAM-TONG.wiki.git .local/wiki-repository
python3 scripts/export_wiki.py --output .local/wiki-repository
git -C .local/wiki-repository add -- Home.md Product-and-Scope.md \
  Requirements-and-Scenarios.md Architecture-and-Decisions.md \
  Research-and-Experiments.md Roadmap-and-Workflow.md _Sidebar.md _Footer.md
git -C .local/wiki-repository diff --cached --check
git -C .local/wiki-repository diff --cached
```

새 파일은 일반 `git diff`에 나타나지 않으므로 내보낸 8개 파일만 먼저 stage하고 `--cached`로 전체 발행 내용을 검토한다. 이미 clone한 Wiki를 갱신할 때는 먼저 기존 편집과 stage한 변경이 없는지 확인하고 원격 변경을 `git pull --ff-only`로 가져온다. 웹에서 수정한 본문이 있으면 원본에 반영한 뒤 내보낸다.

검토한 변경을 commit·push한다. 다른 페이지·기존 commit·사용자의 편집은 보존하며 강제 push하지 않는다. 공개 페이지의 탐색·원본 대응과 원격 commit을 확인해야 GitHub Wiki 발행 완료로 기록한다.
