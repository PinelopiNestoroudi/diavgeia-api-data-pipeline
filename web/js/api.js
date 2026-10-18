// One request controller per view prevents stale responses from updating the UI.
const active = new Map();
export async function request(view, endpoint, params = {}) {
  active.get(view)?.abort();
  const controller = new AbortController();
  active.set(view, controller);
  const timeout = setTimeout(() => controller.abort('timeout'), 120000);
  try {
    const response = await fetch(`${endpoint}?${new URLSearchParams(params)}`, {signal: controller.signal});
    let data;
    try { data = await response.json(); }
    catch { throw new Error('The local service returned invalid JSON.'); }
    if (!response.ok) throw new Error(data.error || 'Request failed.');
    if (active.get(view) !== controller) return null;
    return data;
  } catch (error) {
    if (active.get(view) !== controller) return null;
    if (controller.signal.aborted) throw new Error('Request timed out. Narrow the query and try again.');
    throw error;
  } finally { clearTimeout(timeout); }
}
