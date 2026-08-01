// GitHub's behaviour: the file table, then the folder's README underneath.

import { formatSize, formatAge } from '../format.js';

export function renderListing(container, data, path) {
  const card = document.createElement('div');
  card.className = 'card';

  const table = document.createElement('table');
  table.className = 'listing';

  const rows = [
    ...data.dirs.map((d) => ({ ...d, icon: '📁' })),
    ...data.files.map((f) => ({ ...f, icon: '📄' })),
  ];

  if (rows.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = 'This folder is empty.';
    card.append(empty);
  } else {
    for (const entry of rows) {
      const tr = document.createElement('tr');
      const nameCell = document.createElement('td');
      const link = document.createElement('a');
      link.href = `#/${path ? `${path}/` : ''}${entry.name}`;
      link.textContent = `${entry.icon} ${entry.name}`;
      nameCell.append(link);

      const metaCell = document.createElement('td');
      metaCell.className = 'meta';
      metaCell.textContent = entry.is_dir
        ? formatAge(entry.mtime)
        : `${formatSize(entry.size)} · ${formatAge(entry.mtime)}`;

      tr.append(nameCell, metaCell);
      table.append(tr);
    }
    card.append(table);
  }

  container.append(card);
  return rows.length === 1 ? '1 entry' : `${rows.length} entries`;
}
