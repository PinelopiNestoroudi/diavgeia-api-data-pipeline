import {request, post, downloadSnapshot, startDownload} from './api.js';
import {byId, message, table, website, utcDate, counters} from './ui.js';

const state = {decisions: [], versions: new Map(), snapshotId: null, complete: false,
  expiresAt: 0, expiryTimer: null, storedCount: null, storageBusy: false, sample: null};

function confirmAction(text, label) {
  const dialog = byId('confirmation');
  byId('confirmation-message').textContent = text;
  byId('confirmation-action').textContent = label;
  dialog.returnValue = 'cancel';
  return new Promise(resolve => {
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), {once: true});
    dialog.showModal();
  });
}

function updateActions() {
  const usable = state.snapshotId && state.decisions.length > 0 && Date.now() < state.expiresAt;
  byId('save-search').textContent = `Save search results (${state.decisions.length})`;
  byId('export-search').textContent = `Export search results (${state.decisions.length})`;
  byId('save-search').disabled = !usable || !state.complete || state.storageBusy || state.sample === null;
  byId('export-search').disabled = !usable || state.storageBusy;
  byId('refresh-count').disabled = state.storageBusy;
  byId('export-stored').disabled = state.storageBusy || !state.storedCount;
  byId('clear-stored').disabled = state.storageBusy || !state.storedCount;
  byId('local-data').setAttribute('aria-busy', String(state.storageBusy));
}

function expireSnapshot() {
  state.snapshotId = null;
  clearTimeout(state.expiryTimer);
  message('snapshot-message', 'Snapshot unavailable or expired. Search again to save or export.', 'warning');
  updateActions();
}

function setSnapshot(data) {
  clearTimeout(state.expiryTimer);
  state.snapshotId = data.snapshot_id;
  state.complete = data.complete;
  state.expiresAt = Date.parse(data.snapshot_expires_at || '');
  if (state.snapshotId) {
    state.expiryTimer = setTimeout(expireSnapshot, Math.max(0, state.expiresAt - Date.now()));
    message('snapshot-message', data.complete
      ? 'Search is read-only. Save or export this exact result set within 10 minutes.'
      : 'PARTIAL SNAPSHOT: saving is disabled. Export contains only retrieved rows and is labelled partial.', data.complete ? 'note' : 'warning');
  } else message('snapshot-message', 'No usable snapshot. Run another search.', 'note');
  updateActions();
}

async function refreshStorage() {
  const data = await request('storage-count', '/api/storage');
  if (!data) throw new Error('Count refresh was superseded. Try again.');
  state.storedCount = data.stored_count;
  state.sample = data.sample;
  byId('stored-count').textContent = data.stored_count;
  byId('storage-mode').textContent = data.sample
    ? 'Synthetic demonstration store · sample.sqlite. Save stores synthetic records only in this default store.'
    : 'Live data store · diavgeia.sqlite. Search never saves automatically.';
  updateActions();
  return data.stored_count;
}

async function storageAction(action) {
  if (state.storageBusy) return;
  state.storageBusy = true; updateActions();
  try { await action(); }
  catch (error) {
    if (error.status === 410) expireSnapshot();
    message('storage-message', error.message || 'Operation failed. Refresh the count before retrying.', 'error');
  } finally { state.storageBusy = false; updateActions(); }
}

byId('refresh-count').addEventListener('click', () => storageAction(async () => {
  const count = await refreshStorage();
  message('storage-message', `Count refreshed. Database contains ${count} unique decisions.`);
}));
byId('save-search').addEventListener('click', () => storageAction(async () => {
  const id = state.snapshotId, count = state.decisions.length;
  if (state.sample && !(await confirmAction(`Save ${count} synthetic demonstration records to the sample database?`, 'Save synthetic records'))) {
    message('storage-message', 'Save cancelled. Database unchanged.'); return;
  }
  message('storage-message', 'Saving the validated search snapshot…');
  const data = await post('/api/storage/save', {snapshot_id: id});
  state.storedCount = data.stored_count; byId('stored-count').textContent = data.stored_count;
  message('storage-message', `Processed ${data.processed} decisions. Database now contains ${data.stored_count} unique decisions. Existing ADAs were updated.`);
}));
byId('export-search').addEventListener('click', () => storageAction(async () => {
  const id = state.snapshotId, partial = !state.complete;
  if (partial && !(await confirmAction('These results are incomplete. Export only the retrieved rows as a partial CSV?', 'Export partial CSV'))) return;
  await downloadSnapshot(id);
  message('storage-message', partial ? 'Partial search CSV download requested. This file does not represent complete results.' : 'Search CSV download requested. No database changes.');
}));
byId('export-stored').addEventListener('click', () => storageAction(async () => {
  const count = await refreshStorage();
  if (!count) { message('storage-message', 'No stored decisions to export.'); return; }
  if (!(await confirmAction(`Export all ${count} currently stored ${state.sample ? 'synthetic ' : ''}decisions to CSV?`, 'Export CSV'))) {
    message('storage-message', 'Export cancelled.'); return;
  }
  // Native download streams to the browser; do not build the stored CSV as a JS Blob.
  startDownload('/api/storage/export.csv');
  message('storage-message', `Download requested for ${count} stored decisions. Check browser downloads for completion. Concurrent changes may affect the export count.`);
}));
byId('clear-stored').addEventListener('click', () => storageAction(async () => {
  const count = await refreshStorage();
  if (!count) { message('storage-message', 'Database already contains 0 decisions.'); return; }
  if (!(await confirmAction(`Delete all ${count} stored ${state.sample ? 'synthetic ' : ''}decisions? This cannot be undone. Current search results and previously downloaded CSV files will remain.`, 'Clear stored decisions'))) {
    message('storage-message', 'Clear cancelled. Database unchanged.'); return;
  }
  const data = await post('/api/storage/clear', {confirm: true});
  state.storedCount = data.stored_count; byId('stored-count').textContent = data.stored_count;
  message('storage-message', `Cleared ${data.processed} decisions. Database now contains ${data.stored_count} decisions. Search results remain available until the snapshot expires.`);
}));
const tabs = [...document.querySelectorAll('[role=tab]')];
function activate(tab) {
  tabs.forEach(item => {
    const selected = item === tab;
    item.setAttribute('aria-selected', String(selected)); item.tabIndex = selected ? 0 : -1;
    byId(item.getAttribute('aria-controls')).hidden = !selected;
  });
}
tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => activate(tab));
  tab.addEventListener('keydown', event => {
    let next;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = tabs.length - 1;
    if (next !== undefined) { event.preventDefault(); activate(tabs[next]); tabs[next].focus(); }
  });
});

function dates() {
  const start = byId('start').value, end = byId('end').value;
  const days = (Date.parse(end) - Date.parse(start)) / 86400000;
  if (!start || !end || !Number.isFinite(days) || days < 0 || days > 179) {
    throw new Error('Choose 1–180 inclusive calendar days, with the start date on or before the end date.');
  }
  return {start, end, days};
}
function renderDecisions() {
  const rows = byId('private-only').checked
    ? state.decisions.filter(row => row.status === 'REVOKED' && row.private_data === 1) : state.decisions;
  table('decision-rows', rows, ['ada', 'subject', row => utcDate(row.issued_at_utc), 'status',
    row => row.private_data === null ? 'Unknown' : row.private_data === 1 ? 'Yes' : 'No']);
  byId('private-only').setAttribute('aria-label', `Show only revoked decisions with private-data indicator (${rows.length} currently visible)`);
}

async function run(form, view, endpoint, params, show) {
  const version = (state.versions.get(view) || 0) + 1;
  state.versions.set(view, version);
  form.setAttribute('aria-busy', 'true');
  message(`${view}-message`, 'Loading…');
  try {
    const data = await request(view, endpoint, params);
    if (data && state.versions.get(view) === version) show(data);
  } catch (error) {
    if (state.versions.get(view) === version) message(`${view}-message`, error.message || 'Request failed.', 'error');
  } finally {
    if (state.versions.get(view) === version) form.setAttribute('aria-busy', 'false');
  }
}

byId('decision-form').addEventListener('submit', event => {
  event.preventDefault();
  try {
    dates();
    const params = Object.fromEntries(new FormData(event.currentTarget));
    state.decisions = []; counters([]); renderDecisions();
    clearTimeout(state.expiryTimer); state.snapshotId = null; updateActions();
    message('snapshot-message', 'Searching… No database changes.');
    run(event.currentTarget, 'decision', '/api/decisions', params, data => {
      if (!Array.isArray(data.rows) || typeof data.complete !== 'boolean') throw new Error('Malformed decision response.');
      state.decisions = data.rows; counters(data.rows); renderDecisions();
      setSnapshot(data);
      const summary = `${data.rows.length} unique decisions retrieved across ${data.pages} ${data.pages === 1 ? 'page' : 'pages'}; ${data.duplicates} duplicate ${data.duplicates === 1 ? 'record' : 'records'} merged.`;
      message('decision-message', data.complete ? (data.rows.length ? summary : 'No decisions matched this query.')
        : `PARTIAL RESULTS: ${summary} ${data.warning}`, data.complete ? '' : 'warning');
    });
  } catch (error) { message('decision-message', error.message, 'error'); }
});
byId('private-only').addEventListener('change', renderDecisions);
byId('next-period').addEventListener('click', () => {
  try {
    const {end, days} = dates();
    const next = new Date(Date.parse(end) + 86400000);
    byId('start').value = next.toISOString().slice(0, 10);
    byId('end').value = new Date(next.valueOf() + days * 86400000).toISOString().slice(0, 10);
    message('decision-message', 'Date range updated. Retrieve decisions to run the new query.');
  } catch (error) { message('decision-message', error.message, 'error'); }
});
byId('organization-form').addEventListener('submit', event => {
  event.preventDefault(); table('organization-rows', [], []);
  run(event.currentTarget, 'organization', '/api/organizations', Object.fromEntries(new FormData(event.currentTarget)), data => {
    if (!Array.isArray(data.rows)) throw new Error('Malformed organization response.');
    table('organization-rows', data.rows, ['uid', 'label', 'category', row => website(row.website)]);
    message('organization-message', data.rows.length ? `${data.rows.length} ${data.rows.length === 1 ? 'organization' : 'organizations'} retrieved.` : 'No organizations found.');
  });
});
byId('unit-form').addEventListener('submit', event => {
  event.preventDefault(); table('unit-rows', [], []);
  run(event.currentTarget, 'unit', '/api/units', Object.fromEntries(new FormData(event.currentTarget)), data => {
    if (!Array.isArray(data.rows)) throw new Error('Malformed unit response.');
    table('unit-rows', data.rows, ['uid', 'label', row => row.active ? 'Yes' : 'No', 'parent_id']);
    message('unit-message', data.rows.length ? `${data.rows.length} active units retrieved.` : 'No active units found.');
  });
});
request('config', '/api/config').then(config => {
  if (!config) return;
  byId('source').textContent = config.sample ? 'SYNTHETIC SAMPLE · Offline demonstration' : 'LIVE API · Diavgeia public data';
  if (config.sample) { byId('org').value = '90000001'; byId('unit-org').value = '90000001'; byId('end').value = '2025-05-31'; }
}).catch(() => message('source', 'Local service unavailable. Restart the Python server.', 'error'));
storageAction(async () => {
  const count = await refreshStorage();
  message('storage-message', `Database contains ${count} unique decisions. Search to retrieve data; Save is a separate action.`);
});
