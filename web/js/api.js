// One request controller per view prevents stale responses from updating the UI.
const active = new Map();

async function checked(response) {
  if (!response.ok) {
    let data;
    try { data = await response.json(); } catch { data = {}; }
    const error = new Error(data.error || 'Local service request failed.');
    error.status = response.status;
    throw error;
  }
  return response;
}

export async function post(endpoint, body) {
  // Mutations are never automatically retried or cancelled: the server may have committed.
  const response = await checked(await fetch(endpoint, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  }));
  return response.json();
}

export function startDownload(url, filename = '') {
  const link = document.createElement('a');
  link.href = url; link.download = filename;
  document.body.append(link); link.click(); link.remove();
}

export async function downloadSnapshot(snapshotId) {
  const response = await checked(await fetch(`/api/snapshot/${encodeURIComponent(snapshotId)}/export.csv`));
  const blob = await response.blob(); // Search snapshots are bounded; stored export uses a native download instead.
  const filename = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') || '')?.[1] || 'search-decisions.csv';
  const url = URL.createObjectURL(blob);
  startDownload(url, filename);
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}
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
    if (!response.ok) { const error = new Error(data.error || 'Request failed.'); error.status = response.status; throw error; }
    if (active.get(view) !== controller) return null;
    return data;
  } catch (error) {
    if (active.get(view) !== controller) return null;
    if (controller.signal.aborted) throw new Error('Request timed out. Narrow the query and try again.');
    throw error;
  } finally { clearTimeout(timeout); }
}
