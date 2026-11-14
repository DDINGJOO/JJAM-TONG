/* A fixed, synthetic product tour. No API access and no live data fallback. */
(() => {
  'use strict';
  const allowed = new Set(['overview', 'map', 'catalog', 'code', 'patterns', 'observability',
    'flow', 'trace', 'infra', 'network', 'cmdb', 'sre', 'security', 'agent', 'automation',
    'connectors', 'governance', 'health']);
  function applyRoute() {
    const requested = location.hash.slice(1);
    if (allowed.has(requested)) navigate(requested);
  }
  window.addEventListener('hashchange', applyRoute);
  applyRoute();
})();
