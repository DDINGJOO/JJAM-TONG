(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const state = {
    snapshots: [], snapOffset: 0, snapMore: false, ref: null, ready: false,
    analyzer: 'wala', methods: [], methodOffset: 0, methodMore: false,
    method: null, inspected: null, traces: [], traceOffset: 0, traceMore: false,
    traceId: null, graphScale: 1, graphCenter: [0, 0], graphBounds: [800, 480], graphRoot: null,
    rev: {}, controllers: {}
  };
  let methodTimer;
  const endpoints = Object.fromEntries(
    ['snapshots', 'snapshot', 'methods', 'graph', 'traces', 'trace', 'context']
      .map(name => [name, '/api/' + name])
  );
  const reasons = {
    ANALYZER_UNRESOLVED: '분석기 전체에 미해결 항목이 있어요',
    ANALYZER_EXCLUDED: '분석기 전체에 제외한 항목이 있어요',
    DANGLING_STATIC_CALLS: '분석 목록 밖으로 이어지는 호출 후보가 있어요',
    DEPTH_LIMIT: '표시 깊이 상한에 도달했어요',
    NODE_LIMIT: '메서드 표시 상한에 도달했어요',
    EDGE_LIMIT: '호출 근거 표시 상한에 도달했어요',
    TIME_BUDGET: '조회 시간 상한에 도달했어요',
    ROOT_NOT_IN_ANALYZER: '이 분석기에 시작 메서드가 없어요',
    HISTORY_NOT_COLLECTED: '선택한 분석 이력이 없어요',
    PARENT_EXTERNAL_OR_NOT_COLLECTED: '수집 범위 밖이거나 수집되지 않은 부모가 있어요',
    BUILD_IDENTITY_MISMATCH: '실행 기록의 빌드가 선택한 분석본과 달라요',
    TELEMETRY_CONFIG_MISMATCH: '실행 기록의 계측 설정이 달라요',
    NO_MATCHING_SPANS: '이 조건에 일치하는 실행 구간이 없어요',
    TRACE_CAPTURE_NOT_CONFIGURED: '실행 기록 파일이 설정되지 않았어요',
    INVALID_SPAN_TIMESTAMP: '시작·종료 시간이 없거나 올바르지 않은 기록이 있어요',
    PER_TRACE_RECORD_LIMIT: '한 Trace의 기록 상한에 도달했어요'
  };
  function el(tag, props = {}, children = []) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (key === 'text') node.textContent = value;
      else if (key === 'class') node.className = value;
      else node.setAttribute(key, value);
    }
    node.append(...children);
    return node;
  }
  function svg(tag, props = {}) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key, value] of Object.entries(props)) node.setAttribute(key, value);
    return node;
  }
  function raw(id, value) { $(id).textContent = value == null ? '' : JSON.stringify(value, null, 2); }
  function status(id, message, kind = '') {
    $(id).className = 'state ' + kind;
    $(id).textContent = message;
  }
  function invalidate(...slots) {
    for (const slot of slots) {
      state.rev[slot] = (state.rev[slot] || 0) + 1;
      state.controllers[slot]?.abort();
    }
  }
  function begin(slot) {
    invalidate(slot);
    return state.rev[slot];
  }
  function current(slot, revision) { return state.rev[slot] === revision; }
  function refParams() { return { run_id: state.ref.run_id, index_sha256: state.ref.index_sha256 }; }
  function exactSymbol(method) { return method ? JSON.stringify(method) : ''; }
  function fullSymbol(method) { return method ? method[0] + ' · ' + method[1] + '#' + method[2] + method[3] : ''; }
  function simpleClass(name) { return String(name || '').split('.').pop(); }
  function classLabel(name, methods = state.methods) {
    const short = simpleClass(name);
    const same = new Set(methods.filter(m => simpleClass(m[1]) === short).map(m => m[1]));
    return same.size > 1 ? short + ' [' + String(name).split('.').slice(0, -1).join('.') + ']' : short;
  }
  function readableDescriptor(descriptor) {
    // Display names only. Exact JVM descriptors remain in details and query keys.
    const names = { B: 'byte', C: 'char', D: 'double', F: 'float', I: 'int',
      J: 'long', S: 'short', Z: 'boolean', V: 'void' };
    let position = 1;
    function type() {
      let dimensions = '';
      while (descriptor[position] === '[') { dimensions += '[]'; position++; }
      const code = descriptor[position++];
      if (code === 'L') {
        const end = descriptor.indexOf(';', position);
        if (end < 0) throw new Error('descriptor');
        const name = descriptor.slice(position, end).split('/').pop().split('$').pop();
        position = end + 1;
        return name + dimensions;
      }
      if (!names[code]) throw new Error('descriptor');
      return names[code] + dimensions;
    }
    try {
      if (descriptor[0] !== '(') return descriptor;
      const args = [];
      while (position < descriptor.length && descriptor[position] !== ')') args.push(type());
      if (descriptor[position++] !== ')') return descriptor;
      return '(' + args.join(', ') + ') → ' + type();
    } catch { return descriptor; }
  }
  function reasonText(values = []) {
    return [...new Set(values)].map(value => reasons[value] || value).join(' · ');
  }
  async function get(name, params = {}, slot = name) {
    const controller = new AbortController();
    state.controllers[slot] = controller;
    const response = await fetch(endpoints[name] + '?' + new URLSearchParams(params), {
      signal: controller.signal, headers: { Accept: 'application/json' }
    });
    let data;
    try { data = await response.json(); }
    catch {
      if (controller.signal.aborted) throw new DOMException('Aborted', 'AbortError');
      throw new Error('서버 응답을 읽을 수 없어요.');
    }
    if (!response.ok) throw new Error(data.message || '조회에 실패했어요.');
    if (controller.signal.aborted) throw new DOMException('Aborted', 'AbortError');
    $('queryTime').textContent = '마지막 조회 ' + new Date().toLocaleTimeString('ko-KR');
    return data;
  }
  async function loadContext() {
    try {
      const data = await get('context');
      $('modeBadge').textContent = '로컬 · 읽기 전용';
      $('sourceBadge').textContent = data.traceSource === 'startup-file-capture'
        ? 'DB 분석본 + 저장된 Trace' : 'DB 분석본 · Trace 미설정';
    } catch { $('sourceBadge').textContent = '연결 상태 확인 실패'; }
  }
  function identityRows(data) {
    const build = data.buildIdentity;
    const fields = [
      ['분석 ID', data.ref.run_id], ['분석 해시', data.ref.index_sha256],
      ['저장소', build.repository], ['커밋', build.revision], ['빌드', build.build],
      ['모듈', build.module], ['JAR 해시', build.artifactSha256],
      ['스키마', data.schema], ['분석 설정 해시', data.analysisConfigSha256]
    ];
    $('identityFields').replaceChildren(...fields.map(([key, value]) =>
      el('div', {}, [el('dt', { text: key }), el('dd', { text: value })])));
    $('identitySummary').textContent = build.module + ' · ' + data.ref.run_id +
      ' · 커밋 ' + build.revision.slice(0, 12);
    const coverage = data.coverage[state.analyzer];
    $('inventorySummary').textContent = '메서드 ' + coverage.inventoryMethods +
      ' · 호출 근거 ' + coverage.indexedCalls + ' · 분석 전체 미해결 ' + coverage.unresolved;
  }
  async function loadSnapshots(reset = false) {
    const revision = begin('snapshots');
    if (reset) { state.snapOffset = 0; state.snapshots = []; }
    $('snapshotList').replaceChildren();
    $('moreSnapshots').hidden = true;
    status('snapshotState', '분석본을 불러오는 중…', 'loading');
    try {
      const data = await get('snapshots', { limit: 50, offset: state.snapOffset });
      if (!current('snapshots', revision)) return;
      state.snapshots.push(...data.snapshots);
      state.snapOffset = data.offset + data.snapshots.length;
      state.snapMore = data.hasMore;
      renderSnapshots();
      $('moreSnapshots').hidden = !data.hasMore;
    } catch (error) {
      if (current('snapshots', revision) && error.name !== 'AbortError')
        status('snapshotState', error.message + ' 목록 새로고침으로 다시 시도해주세요.', 'error');
    }
  }
  function renderSnapshots() {
    const filter = $('snapshotFilter').value.toLocaleLowerCase();
    const matching = state.snapshots.filter(item =>
      [item.ref.run_id, item.ref.index_sha256, ...Object.values(item.buildIdentity)]
        .join(' ').toLocaleLowerCase().includes(filter));
    $('snapshotList').replaceChildren(...matching.map(item => {
      const active = state.ref && item.ref.run_id === state.ref.run_id &&
        item.ref.index_sha256 === state.ref.index_sha256;
      const button = el('button', { class: 'snapshot' + (active ? ' active' : ''),
        'aria-pressed': String(!!active), 'data-run': item.ref.run_id }, [
        el('strong', { text: item.buildIdentity.build }),
        el('small', { text: item.ref.run_id }),
        el('small', { text: item.buildIdentity.module + ' · ' + item.buildIdentity.revision.slice(0, 12) }),
        el('small', { text: '분석 해시 ' + item.ref.index_sha256.slice(0, 12) })
      ]);
      button.addEventListener('click', () => selectSnapshot(item.ref));
      return button;
    }));
    status('snapshotState', !state.snapshots.length ? '저장된 분석본이 없어요.'
      : !matching.length ? '현재 불러온 목록에 검색 결과가 없어요.'
      : matching.length + '개 · 분석 ID 문자열 역순 (시간순 아님)');
  }
  function clearGraph(message = '메서드를 선택하면 호출 후보를 조회해요.') {
    invalidate('graph');
    state.method = null;
    state.inspected = null;
    state.graphRoot = null;
    $('graphLayer').replaceChildren();
    $('graphNotes').replaceChildren();
    $('graphCounts').textContent = '';
    $('graphTitle').textContent = '호출 후보 그래프';
    $('methodDetail').hidden = true;
    raw('graphRaw', null);
    status('graphState', message);
  }
  function clearMethods(message = '메서드를 불러오는 중…') {
    invalidate('methods');
    state.methods = [];
    state.methodOffset = 0;
    $('methodList').replaceChildren();
    $('moreMethods').hidden = true;
    status('methodState', message, 'loading');
    clearGraph();
  }
  async function selectSnapshot(ref) {
    clearTimeout(methodTimer);
    invalidate('snapshot', 'methods', 'graph', 'traces', 'trace');
    const revision = begin('selected');
    state.ref = ref;
    state.ready = false;
    clearMethods();
    $('traceList').replaceChildren();
    $('traceView').replaceChildren();
    $('identityFields').replaceChildren();
    $('identityTitle').textContent = '분석본을 확인하는 중…';
    $('identityAssurance').textContent = '';
    $('identitySummary').textContent = ref.run_id;
    $('buildPickerSummary').textContent = ref.run_id + ' · 확인 중';
    $('inventorySummary').textContent = '';
    $('traceTitle').textContent = '저장된 실행 기록';
    raw('snapshotRaw', null);
    raw('traceRaw', null);
    status('traceState', '선택한 분석본과 실행 기록을 대조해요.');
    renderSnapshots();
    $('welcome').hidden = true;
    $('evidence').hidden = false;
    try {
      const data = await get('snapshot', refParams());
      if (!current('selected', revision)) return;
      $('identityTitle').textContent = data.buildIdentity.build;
      $('identityAssurance').textContent = data.identityAssurance;
      identityRows(data);
      raw('snapshotRaw', data);
      state.ready = true;
      $('buildPickerSummary').textContent = data.buildIdentity.build + ' · ' + data.ref.run_id;
      $('buildPicker').open = false;
      loadMethods(true);
      loadTraces(true);
      if (state.traceId) loadTrace();
    } catch (error) {
      if (!current('selected', revision) || error.name === 'AbortError') return;
      $('identityTitle').textContent = '분석본을 조회하지 못했어요';
      $('buildPickerSummary').textContent = ref.run_id + ' · 조회 실패';
      $('buildPicker').open = true;
      $('identityAssurance').textContent = error.message;
      status('methodState', error.message, 'error');
      status('traceState', error.message, 'error');
    }
  }
  async function loadMethods(reset = false) {
    if (!state.ready) return;
    if (reset) clearMethods();
    const revision = begin('methods');
    status('methodState', '메서드를 불러오는 중…', 'loading');
    $('moreMethods').hidden = true;
    try {
      const data = await get('methods', { ...refParams(), analyzer: state.analyzer,
        q: $('methodSearch').value, limit: 80, offset: state.methodOffset });
      if (!current('methods', revision)) return;
      state.methods.push(...data.methods);
      state.methodOffset = data.offset + data.methods.length;
      renderMethods();
      status('methodState', !data.total ? '검색 조건에 맞는 메서드가 없어요.'
        : data.total + '개 중 ' + state.methods.length + '개 · ' + data.analyzer);
      $('moreMethods').hidden = !data.hasMore;
      if (reset && state.methods.length) {
        selectMethod(state.methods.find(m => simpleClass(m[1]) === 'BoardController' && m[2] === 'create')
          || state.methods[0]);
        const active = $('methodList').querySelector('.active');
        if (active) $('methodList').scrollTop = active.offsetTop;
      }
    } catch (error) {
      if (current('methods', revision) && error.name !== 'AbortError')
        status('methodState', error.message + ' 검색 조건을 바꿔 다시 시도해주세요.', 'error');
    }
  }
  function renderMethods() {
    $('methodList').replaceChildren(...state.methods.map(method => {
      const active = exactSymbol(state.method) === exactSymbol(method);
      const button = el('button', { class: 'method' + (active ? ' active' : ''),
        'aria-pressed': String(active), title: fullSymbol(method) }, [
        el('strong', { text: classLabel(method[1]) + '.' + method[2] }),
        el('small', { text: readableDescriptor(method[3]) })
      ]);
      button.addEventListener('click', () => selectMethod(method));
      return button;
    }));
  }
  function selectMethod(method) {
    state.method = method;
    state.inspected = method;
    renderMethods();
    $('graphTitle').textContent = classLabel(method[1]) + '.' + method[2];
    $('symbolDetail').textContent = fullSymbol(method);
    $('methodDetail').hidden = false;
    loadGraph();
  }
  async function loadGraph() {
    if (!state.ready || !state.method) return;
    const revision = begin('graph');
    $('graphLayer').replaceChildren();
    $('graphNotes').replaceChildren();
    $('graphCounts').textContent = '';
    raw('graphRaw', null);
    status('graphState', '호출 후보를 조회하는 중…', 'loading');
    try {
      const [module, clazz, name, descriptor] = state.method;
      const data = await get('graph', { ...refParams(), analyzer: state.analyzer, module,
        class: clazz, name, descriptor, depth: $('depth').value, nodes: 80, edges: 200 });
      if (!current('graph', revision)) return;
      raw('graphRaw', data);
      renderGraph(data);
    } catch (error) {
      if (current('graph', revision) && error.name !== 'AbortError')
        status('graphState', error.message + ' 깊이를 줄이거나 메서드를 다시 선택해주세요.', 'error');
    }
  }
  function renderGraph(data) {
    const methods = data.methods || [], calls = data.calls || [], root = data.request.root;
    const rootKey = exactSymbol(root);
    const layer = $('graphLayer');
    layer.replaceChildren();
    $('graphCounts').textContent = '메서드 ' + methods.length + ' · 호출 근거 ' + calls.length;
    const notes = [];
    if (data.reasons.length) notes.push(reasonText(data.reasons));
    if (data.coverage.inventoryMethods !== undefined) {
      notes.push('분석기 전체: 메서드 ' + data.coverage.inventoryMethods + ', 미해결 ' +
        data.coverage.unresolved + ', 목록 밖 호출 ' + data.coverage.danglingCalls +
        '. 선택한 흐름에서 발생했다는 뜻은 아니에요.');
    }
    $('graphNotes').replaceChildren(...notes.map(text => el('div', { class: 'notice', text })));
    if (!methods.length) {
      status('graphState', '표시할 메서드가 없어요. ' + reasonText(data.reasons));
      return; // Never invent even a root when the analyzer did not return it.
    }
    status('graphState', data.status === 'PARTIAL' ? '부분 결과 · 알려진 분석 한계가 있어요.' : '정적 호출 후보');
    const map = new Map(methods.map(method => [exactSymbol(method), method]));
    const adjacency = new Map([...map.keys()].map(key => [key, []]));
    const keyOf = item => exactSymbol([item.module, item.class, item.name, item.descriptor]);
    for (const call of calls) {
      const from = keyOf(call.caller), to = keyOf(call.target);
      if (map.has(from) && map.has(to)) adjacency.get(from).push(to);
    }
    const levels = new Map(), queue = [];
    if (map.has(rootKey)) { levels.set(rootKey, 0); queue.push(rootKey); }
    for (let i = 0; i < queue.length; i++) {
      for (const to of adjacency.get(queue[i]) || []) {
        if (!levels.has(to)) { levels.set(to, levels.get(queue[i]) + 1); queue.push(to); }
      }
    }
    for (const key of map.keys()) if (!levels.has(key)) levels.set(key, 0);
    const groups = new Map();
    for (const [key, level] of levels) {
      if (!groups.has(level)) groups.set(level, []);
      groups.get(level).push(key);
    }
    const positions = new Map(), nodeWidth = 230, nodeHeight = 68;
    for (const [level, keys] of groups) {
      keys.sort().forEach((key, index) => positions.set(key, { x: 40 + level * 300, y: 40 + index * 106 }));
    }
    state.graphBounds = [
      Math.max(400, ...[...positions.values()].map(pos => pos.x + nodeWidth + 60)),
      Math.max(240, ...[...positions.values()].map(pos => pos.y + nodeHeight + 50))
    ];
    const defs = svg('defs');
    const marker = svg('marker', { id: 'candidate-arrow', markerWidth: 7, markerHeight: 7,
      refX: 6, refY: 3.5, orient: 'auto', markerUnits: 'strokeWidth' });
    marker.append(svg('path', { d: 'M0,0 L7,3.5 L0,7 Z', fill: '#6893af' }));
    defs.append(marker);
    layer.append(defs);
    for (const call of calls) {
      const from = positions.get(keyOf(call.caller)), to = positions.get(keyOf(call.target));
      if (!from || !to) continue;
      const x1 = from.x + nodeWidth, y1 = from.y + nodeHeight / 2, y2 = to.y + nodeHeight / 2;
      const bend = from.x >= to.x
        ? ' C ' + (x1 + 70) + ' ' + (y1 - 70) + ', ' + (to.x - 55) + ' ' + (y2 - 70)
        : ' C ' + (x1 + 32) + ' ' + y1 + ', ' + (to.x - 32) + ' ' + y2;
      const edge = svg('path', { d: 'M ' + x1 + ' ' + y1 + bend + ', ' + to.x + ' ' + y2,
        class: 'edge', 'marker-end': 'url(#candidate-arrow)' });
      const title = svg('title');
      title.textContent = call.kind + ' · 코드상 호출 후보';
      edge.append(title);
      layer.append(edge);
    }
    for (const [key, method] of map) {
      const position = positions.get(key);
      const node = svg('g', { class: 'node' + (key === rootKey ? ' root' : ''),
        transform: 'translate(' + position.x + ' ' + position.y + ')',
        tabindex: 0, role: 'button', 'aria-label': classLabel(method[1], methods) + '.' + method[2] + readableDescriptor(method[3]) });
      const title = svg('title');
      title.textContent = fullSymbol(method);
      const classText = svg('text', { x: 14, y: 25, class: 'class-text' });
      const label = classLabel(method[1], methods);
      classText.textContent = label.length > 27 ? label.slice(0, 25) + '…' : label;
      const methodText = svg('text', { x: 14, y: 48, class: 'method-text' });
      const methodLabel = method[2] + readableDescriptor(method[3]).split(' → ')[0];
      methodText.textContent = methodLabel.length > 33 ? methodLabel.slice(0, 31) + '…' : methodLabel;
      node.append(svg('rect', { width: nodeWidth, height: nodeHeight, rx: 10 }), title, classText, methodText);
      const inspect = () => {
        layer.querySelectorAll('.selected').forEach(item => item.classList.remove('selected'));
        node.classList.add('selected');
        $('methodDetail').open = true;
        state.inspected = method;
        $('symbolDetail').textContent = fullSymbol(method);
        $('methodDetail').hidden = false;
      };
      node.addEventListener('click', inspect);
      node.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); inspect(); }
      });
      layer.append(node);
    }
    state.graphRoot = positions.get(rootKey) || positions.values().next().value;
    focusGraph();
  }
  function transformGraph() {
    const [width, height] = state.graphBounds;
    const [cx, cy] = state.graphCenter;
    const scale = state.graphScale;
    $('graphSvg').setAttribute('viewBox',
      [cx - width / scale / 2, cy - height / scale / 2, width / scale, height / scale].join(' '));
    const pixelScale = $('graphSvg').getScreenCTM()?.a || 1;
    $('graphSvg').classList.toggle('overview', pixelScale < 0.65);
    $('graphSvg').classList.toggle('dense-overview', pixelScale < 0.4);
    $('graphZoomHint').textContent = pixelScale < 0.65
      ? '전체 관계를 보는 배율이에요. 확대하거나 시작점으로 돌아가면 메서드를 읽을 수 있어요.'
      : '메서드 보기 · 빈 곳을 드래그해 이동하고 노드를 선택해 상세를 확인하세요.';
  }
  function fitGraph() {
    state.graphScale = 1;
    state.graphCenter = state.graphBounds.map(value => value / 2);
    transformGraph();
  }
  function focusGraph() {
    if (!state.graphRoot) return;
    const rect = $('graphViewport').getBoundingClientRect();
    const [width, height] = state.graphBounds;
    const fit = Math.min((rect.width || 650) / width, (rect.height || 450) / height);
    state.graphScale = Math.min(5, Math.max(1, 0.9 / fit));
    const horizontalOffset = rect.width < 500 ? 0.05 : 0.22;
    state.graphCenter = [state.graphRoot.x + 115 + width / state.graphScale * horizontalOffset,
      state.graphRoot.y + 34 + height / state.graphScale * 0.2];
    transformGraph();
  }
  async function loadTraces(reset = false) {
    const revision = begin('traces');
    if (reset) { state.traceOffset = 0; state.traces = []; }
    $('moreTraces').hidden = true;
    status('traceListState', '저장된 실행 기록을 불러오는 중…', 'loading');
    try {
      const data = await get('traces', { limit: 50, offset: state.traceOffset });
      if (!current('traces', revision)) return;
      state.traces.push(...data.traces);
      state.traceOffset = data.offset + data.traces.length;
      $('traceSource').textContent = data.source === 'startup-file-capture'
        ? '서버 시작 시 읽은 실행 기록이에요. 실시간 수집 화면은 아니에요.'
        : '실행 기록 파일이 설정되지 않았어요.';
      renderTraces();
      status('traceListState', state.traces.length ? state.traces.length + '개 Trace' : '저장된 실행 기록이 없어요.');
      $('moreTraces').hidden = !data.hasMore;
    } catch (error) {
      if (current('traces', revision) && error.name !== 'AbortError') status('traceListState', error.message, 'error');
    }
  }
  function renderTraces() {
    $('traceList').replaceChildren(...state.traces.map(trace => {
      const button = el('button', { class: 'trace-item' + (state.traceId === trace.traceId ? ' active' : ''),
        'aria-pressed': String(state.traceId === trace.traceId) }, [
        el('strong', { text: trace.traceId }),
        el('small', { text: '수집 기록 ' + trace.spanRecords + '개' })
      ]);
      button.addEventListener('click', () => {
        state.traceId = trace.traceId;
        renderTraces();
        loadTrace();
      });
      return button;
    }));
  }
  function interval(span) {
    try {
      if (span.startTimeUnixNano == null || span.endTimeUnixNano == null) return null;
      const start = BigInt(span.startTimeUnixNano), end = BigInt(span.endTimeUnixNano);
      if (end < start || end - start > BigInt(Number.MAX_SAFE_INTEGER)) return null;
      return { start, end, duration: Number(end - start) / 1e6 };
    } catch { return null; }
  }
  async function loadTrace() {
    if (!state.ready || !state.traceId) return;
    const revision = begin('trace');
    $('traceView').replaceChildren();
    raw('traceRaw', null);
    status('traceState', '선택한 빌드와 실행 기록을 대조하는 중…', 'loading');
    try {
      const data = await get('trace', { ...refParams(), trace_id: state.traceId });
      if (!current('trace', revision)) return;
      raw('traceRaw', data);
      renderTrace(data);
    } catch (error) {
      if (current('trace', revision) && error.name !== 'AbortError') status('traceState', error.message, 'error');
    }
  }
  function renderTrace(data) {
    $('traceTitle').textContent = 'Trace ' + data.traceId.slice(0, 12);
    const holder = $('traceView');
    holder.replaceChildren();
    const explanation = data.status === 'MISMATCH'
      ? '선택한 빌드와 실행 기록이 달라요. 메서드를 연결하지 않았어요.'
      : data.status === 'OBSERVED' ? '수집된 실행 구간과 부모 관계예요.'
      : data.status === 'PARTIAL' ? '부분 수집 · 미해결 정보와 수집 범위를 함께 확인해주세요.'
      : reasonText([data.reason || 'NO_MATCHING_SPANS']);
    $('traceState').className = 'state';
    $('traceState').replaceChildren(
      el('span', { class: 'status ' + String(data.status).toLowerCase(), text: data.status }),
      document.createTextNode(' ' + explanation));
    const rejectionReasons = (data.rejected || []).map(item => item.reason);
    if (data.status === 'MISMATCH') {
      holder.append(el('div', { class: 'notice bad', text: '거부한 실행 구간 ' +
        (data.rejected || []).length + '개 · ' + reasonText(rejectionReasons) }));
      return;
    }
    const spans = data.spans || [], byParent = new Map(), ids = new Set(spans.map(span => span.spanId));
    const windows = spans.map(interval).filter(Boolean);
    const min = windows.reduce((value, window) => value == null || window.start < value ? window.start : value, null);
    const max = windows.reduce((value, window) => value == null || window.end > value ? window.end : value, null);
    const range = min == null || max - min > BigInt(Number.MAX_SAFE_INTEGER) ? null : Number(max - min);
    if (range != null) holder.append(el('p', { class: 'helper', text:
      '수집된 구간의 시간 범위 ' + (range / 1e6).toFixed(2) + ' ms · 막대의 겹침은 시간 중첩을 나타내요.' }));
    for (const span of spans) {
      if (span.parentSpanId && ids.has(span.parentSpanId)) {
        if (!byParent.has(span.parentSpanId)) byParent.set(span.parentSpanId, []);
        byParent.get(span.parentSpanId).push(span);
      }
    }
    const children = new Set([...byParent.values()].flat().map(span => span.spanId)), seen = new Set();
    function draw(span, depth = 0) {
      if (seen.has(span.spanId)) {
        holder.append(el('div', { class: 'notice', text: '순환·중복 부모 관계 · ' + span.spanId }));
        return;
      }
      seen.add(span.spanId);
      const row = el('article', { class: 'trace-row' + (span.error ? ' error' : '') });
      row.style.marginLeft = Math.min(depth, 6) * 12 + 'px';
      const label = span.class && span.method
        ? simpleClass(span.class) + '.' + span.method : '프레임워크 구간 · 메서드 식별 없음';
      const time = interval(span);
      row.append(el('strong', { text: label }), el('p', { text:
        (time ? time.duration.toFixed(2) + ' ms' : '시간 정보 없음') +
        (span.error ? ' · 오류' : '') + ' · span ' + span.spanId }));
      if (time && range != null) {
        const timing = el('div', { class: 'span-timing', role: 'img', 'aria-label': '수집 범위 내 실행 시간' });
        const bar = el('span', { class: 'time-bar' });
        bar.style.marginLeft = (range ? Number(time.start - min) / range * 100 : 0) + '%';
        bar.style.width = (range ? Number(time.end - time.start) / range * 100 : 100) + '%';
        timing.append(bar);
        row.append(timing);
      }
      if (span.class && span.method) {
        row.append(el('p', { class: span.symbolStatus === 'UNRESOLVED_CODE_SYMBOL' ? 'error-text' : '',
          text: span.symbolStatus === 'unique-name-resolved'
            ? '이름 후보 1개 · descriptor 추론' : '메서드 식별 미해결 · 후보 ' + span.symbolCandidates.length + '개' }));
        if (span.symbolStatus === 'UNRESOLVED_CODE_SYMBOL')
          row.append(el('p', { text: span.symbolCandidates.map(candidate =>
            candidate.name + readableDescriptor(candidate.descriptor)).join(' / ') }));
      }
      const details = el('details', { class: 'span-details' }, [
        el('summary', { text: '메서드 식별·문맥 상세' }),
        el('p', { text: (span.class || '클래스 없음') + '#' + (span.method || '메서드 없음') }),
        el('p', { text: 'span ' + span.spanId + ' · 부모 ' + (span.parentSpanId || '없음') })
      ]);
      for (const candidate of span.symbolCandidates || [])
        details.append(el('code', { text: fullSymbol([candidate.module, candidate.class, candidate.name, candidate.descriptor]) }));
      for (const link of span.links || [])
        details.append(el('p', { text: '문맥 링크 · Trace ' + link.traceId + ' / span ' + link.spanId }));
      row.append(details);
      holder.append(row);
      for (const child of byParent.get(span.spanId) || []) draw(child, depth + 1);
    }
    spans.filter(span => !children.has(span.spanId)).forEach(span => draw(span));
    spans.filter(span => !seen.has(span.spanId)).forEach(span => draw(span));
    for (const edge of (data.edges || []).filter(edge => edge.parentState === 'external-or-not-collected'))
      holder.append(el('div', { class: 'trace-row external', text: '부모 미수집 · ' +
        edge.parentSpanId + ' → ' + edge.childSpanId + ' (부모 span은 추가하지 않았어요)' }));
    const messages = [...(data.collectionReasons || []), ...rejectionReasons, ...(data.reason ? [data.reason] : [])];
    if (messages.length) holder.append(el('div', { class: 'notice', text: reasonText(messages) }));
    holder.append(el('p', { class: 'helper',
      text: '부모·문맥 링크는 동기 코드 호출의 증거가 아니에요. 기록이 없다는 사실만으로 미실행을 단정할 수 없어요.' }));
  }
  $('snapshotFilter').addEventListener('input', renderSnapshots);
  $('refreshSnapshots').addEventListener('click', () => loadSnapshots(true));
  $('moreSnapshots').addEventListener('click', () => loadSnapshots());
  $('analyzer').addEventListener('change', event => {
    state.analyzer = event.target.value;
    $('inventorySummary').textContent = '';
    loadMethods(true);
    // Identity is immutable; update only the selected analyzer's summary.
    const ref = state.ref, selected = state.snapshots.find(item =>
      item.ref.run_id === ref?.run_id && item.ref.index_sha256 === ref?.index_sha256);
    if (selected) identityRows(selected);
  });
  $('methodSearch').addEventListener('input', () => {
    clearTimeout(methodTimer);
    clearMethods('검색 조건을 적용하는 중…');
    methodTimer = setTimeout(() => loadMethods(true), 280);
  });
  $('moreMethods').addEventListener('click', () => loadMethods());
  $('depth').addEventListener('change', loadGraph);
  $('focusRoot').addEventListener('click', () => { if (state.inspected) selectMethod(state.inspected); });
  $('zoomIn').addEventListener('click', () => { state.graphScale = Math.min(5, state.graphScale * 1.3); transformGraph(); });
  $('zoomOut').addEventListener('click', () => { state.graphScale = Math.max(0.3, state.graphScale / 1.3); transformGraph(); });
  $('zoomFit').addEventListener('click', fitGraph);
  $('zoomRoot').addEventListener('click', focusGraph);
  $('moreTraces').addEventListener('click', () => loadTraces());
  const tabs = [...document.querySelectorAll('.tab')];
  function selectTab(button) {
    for (const tab of tabs) { tab.classList.toggle('active', tab === button); tab.setAttribute('aria-selected', String(tab === button)); }
    $('staticPane').hidden = button.dataset.tab !== 'static';
    $('tracePane').hidden = button.dataset.tab !== 'trace';
  }
  tabs.forEach((button, index) => {
    button.addEventListener('click', () => selectTab(button));
    button.addEventListener('keydown', event => {
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        event.preventDefault();
        const next = tabs[(index + (event.key === 'ArrowLeft' ? tabs.length - 1 : 1)) % tabs.length];
        next.focus();
        selectTab(next);
      }
    });
  });
  let drag;
  $('graphSvg').addEventListener('pointerdown', event => {
    if (event.target.closest('.node') || !event.isPrimary) return;
    drag = { x: event.clientX, y: event.clientY, center: [...state.graphCenter] };
    $('graphSvg').setPointerCapture(event.pointerId);
  });
  $('graphSvg').addEventListener('pointermove', event => {
    if (!drag) return;
    const ctm = $('graphSvg').getScreenCTM();
    if (!ctm) return;
    state.graphCenter = [
      drag.center[0] - (event.clientX - drag.x) / ctm.a,
      drag.center[1] - (event.clientY - drag.y) / ctm.d
    ];
    transformGraph();
  });
  for (const event of ['pointerup', 'pointercancel', 'lostpointercapture'])
    $('graphSvg').addEventListener(event, () => { drag = null; });
  let graphWidth = 0;
  new ResizeObserver(entries => {
    const width = entries[0].contentRect.width;
    if (width > 0 && Math.abs(width - graphWidth) > 1) {
      graphWidth = width;
      focusGraph();
    }
  }).observe($('graphViewport'));
  loadContext();
  loadSnapshots(true);
})();
