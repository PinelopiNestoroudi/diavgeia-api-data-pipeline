export const byId = id => document.getElementById(id);
export function message(id, text, kind = '') {
  const node = byId(id);
  node.textContent = text;
  node.className = kind;
}
export function table(id, rows, columns) {
  const fragment = document.createDocumentFragment();
  for (const row of rows) {
    const tr = document.createElement('tr');
    for (const column of columns) {
      const td = document.createElement('td');
      const value = typeof column === 'function' ? column(row) : row[column];
      if (value instanceof Node) td.append(value);
      else td.textContent = value === null || value === undefined || value === '' ? '—' : String(value);
      tr.append(td);
    }
    fragment.append(tr);
  }
  byId(id).replaceChildren(fragment);
}
export function website(value) {
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol)) return '—';
    const anchor = document.createElement('a');
    anchor.href = url.href; anchor.textContent = url.hostname;
    anchor.target = '_blank'; anchor.rel = 'noopener noreferrer';
    return anchor;
  } catch { return '—'; }
}
export function utcDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? '—' : date.toISOString().replace('T', ' ').slice(0, 19);
}
export function counters(rows) {
  const revoked = rows.filter(row => row.status === 'REVOKED');
  const values = [['Retrieved', rows.length], ['Revoked', revoked.length],
    ['Revoked + private indicator', revoked.filter(row => row.private_data === 1).length]];
  byId('decision-summary').replaceChildren(...values.map(([label, count]) => {
    const item = document.createElement('div'); item.className = 'metric';
    const strong = document.createElement('strong'); strong.textContent = count;
    item.append(strong, document.createTextNode(label)); return item;
  }));
}
