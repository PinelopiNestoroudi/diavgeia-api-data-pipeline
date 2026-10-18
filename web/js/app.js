import {request} from './api.js';
import {byId, message, table, website, utcDate, counters} from './ui.js';

const state = {decisions: [], versions: new Map()};
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
    run(event.currentTarget, 'decision', '/api/decisions', params, data => {
      if (!Array.isArray(data.rows) || typeof data.complete !== 'boolean') throw new Error('Malformed decision response.');
      state.decisions = data.rows; counters(data.rows); renderDecisions();
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
