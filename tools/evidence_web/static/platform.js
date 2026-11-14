/* Product navigation around the live consumer. Synthetic fixtures stay in /demo. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const pages = {
    services: ['SERVICE INTELLIGENCE', '서비스 분석', '코드상 호출 후보와 실제 실행을, 같은 빌드의 근거로 살펴봅니다.', 'catalog'],
    overview: ['ORGANIZATION OVERVIEW', '전사 현황', '연결된 근거와 앞으로 연결할 영역을 한눈에 확인합니다.', 'overview'],
    infra: ['INFRASTRUCTURE & ASSETS', '인프라·자산', '워크로드·네트워크·자산 관계를 연결할 영역입니다. 현재 데이터 연결 전이에요.', 'infra'],
    sre: ['RELIABILITY & SECURITY', '운영·보안', '서비스의 신뢰성과 보안 사건을 함께 조사할 영역입니다. 현재 데이터 연결 전이에요.', 'sre'],
    automation: ['CONTINUOUS AUTOMATION', '자동화', '발견·분석·갱신 작업의 흐름과 실행 이력을 연결할 영역입니다.', 'automation'],
    connectors: ['PLATFORM MANAGEMENT', '플랫폼 관리', '데이터 연결과 플랫폼 상태를 관리할 영역입니다.', 'connectors']
  };
  const node = (tag, text, className) => {
    const result = document.createElement(tag);
    if (text) result.textContent = text;
    if (className) result.className = className;
    return result;
  };
  function action(text, target, demo = false) {
    const result = node(demo ? 'a' : 'button', text, 'btn' + (demo ? '' : ' primary'));
    if (demo) result.href = '/demo#' + pages[target][3];
    else { result.type = 'button'; result.dataset.page = target; }
    return result;
  }
  function placeholder(key) {
    const host = $('platformPlaceholder');
    host.replaceChildren();
    const panel = node('div', '', 'panel');
    panel.append(node('span', key === 'overview' ? '⌁' : '⬡', 'placeholder-icon'));
    panel.append(node('span', key === 'overview' ? '실제 조회 연결' : '데이터 연결 전', 'badge ' + (key === 'overview' ? 'green' : 'amber')));
    const heading = node('h2', key === 'overview' ? '코드와 실행 근거부터 연결했습니다.' : pages[key][1] + '의 실제 데이터는 아직 연결 전이에요.');
    heading.id = 'placeholderTitle';
    panel.append(heading);
    panel.append(node('p', key === 'overview'
      ? '현재 연결된 범위는 로컬 DB의 버전별 코드 분석본과 서버 시작 시 읽은 실행 기록입니다. 서비스 분석에서 메서드와 Trace를 확인할 수 있어요.'
      : '이 영역도 JJAM-TONG의 구현 범위입니다. 지금은 실제 수집 결과가 없으며, 제품 데모에서 완성될 화면의 탐색 흐름을 확인할 수 있어요.'));
    const actions = node('div', '', 'actions');
    actions.append(action('연결된 서비스 분석', 'services'), action('제품 데모로 보기 ↗', key, true));
    panel.append(actions);
    host.append(panel);
    if (key === 'overview') {
      const cards = node('div', '', 'platform-capabilities');
      for (const [title, status, description] of [
        ['버전별 코드 관계', '실제 조회', '분석본을 직접 선택하고 메서드의 정적 호출 후보를 살펴봅니다.'],
        ['요청 실행 기록', '저장된 캡처', '저장된 Trace를 선택한 빌드와 대조합니다. 실시간 유입 기록은 아닙니다.'],
        ['인프라·자산·보안', '연결 전', '제품 데모에서 전체 범위의 사용 흐름을 확인할 수 있습니다.']
      ]) {
        const card = node('article', '', 'panel');
        card.append(node('span', status, 'badge'), node('h3', title), node('p', description));
        cards.append(card);
      }
      host.append(cards);
    }
  }
  function show(key, updateUrl = true) {
    if (!pages[key]) key = 'services';
    const [eyebrow, title, description] = pages[key];
    $('platformTitle').textContent = title;
    $('platformDescription').textContent = description;
    $('platformEyebrow').textContent = eyebrow;
    $('platformCrumb').textContent = title;
    document.title = 'JJAM-TONG · ' + title;
    for (const button of document.querySelectorAll('[data-page]')) {
      const active = button.dataset.page === key;
      if (button.closest('nav')) {
        button.classList.toggle('active', active);
        if (active) button.setAttribute('aria-current', 'page');
        else button.removeAttribute('aria-current');
      }
    }
    $('liveWorkspace').hidden = key !== 'services';
    $('platformPlaceholder').hidden = key === 'services';
    $('connectionBanner').hidden = key !== 'services';
    $('pageDataMode').textContent = key === 'services' ? '실제 로컬 근거' : key === 'overview' ? '연결 현황' : '데이터 연결 전';
    $('pageDataMode').className = 'badge ' + (key === 'services' ? 'green' : 'amber');
    if (key !== 'services') placeholder(key);
    if (updateUrl) history.replaceState(null, '', '#' + key);
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('button[data-page]');
    if (button) show(button.dataset.page);
  });
  window.addEventListener('hashchange', () => show(location.hash.slice(1), false));
  show(location.hash.slice(1), false);
})();
