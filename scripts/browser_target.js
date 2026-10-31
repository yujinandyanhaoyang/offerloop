// Pure target selection shared by both browser drivers. Never falls back to another site.
function selectTarget(pages, { id, url, hosts = [] } = {}) {
  const matches = pages.filter(page => {
    let parsed;
    try { parsed = new URL(page.url); } catch { return false; }
    if (!['http:', 'https:'].includes(parsed.protocol)) return false;
    if (hosts.length && !hosts.includes(parsed.hostname)) return false;
    if (id && page.id !== id) return false;
    if (url && page.url !== url) return false;
    return true;
  });
  if (matches.length !== 1) throw new Error(matches.length ?
    'AMBIGUOUS_TARGET: specify --url <exact URL> or --tab <ID>' : 'TARGET_NOT_FOUND: no matching page; no fallback performed');
  return matches[0];
}
module.exports = { selectTarget };
