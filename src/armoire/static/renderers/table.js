export function renderTable(container, data, path, reload) {
  const card = document.createElement('div');
  card.className = 'card';

  const head = document.createElement('div');
  head.className = 'card-head';
  head.textContent = `${data.total_rows.toLocaleString()} rows × ${data.columns.length} columns`;
  card.append(head);

  const scroll = document.createElement('div');
  scroll.className = 'table-scroll';
  const table = document.createElement('table');
  table.className = 'datatable';

  const headerRow = document.createElement('tr');
  for (const column of data.columns) {
    const th = document.createElement('th');
    th.textContent = column.name;
    th.title = column.dtype;
    headerRow.append(th);
  }
  table.append(headerRow);

  for (const row of data.rows) {
    const tr = document.createElement('tr');
    for (const cell of row) {
      const td = document.createElement('td');
      td.textContent = cell === null ? '—' : cell;
      tr.append(td);
    }
    table.append(tr);
  }

  scroll.append(table);
  card.append(scroll);

  const lastPage = Math.max(0, Math.ceil(data.total_rows / data.page_size) - 1);
  const pager = document.createElement('div');
  pager.className = 'pager';

  const previous = document.createElement('button');
  previous.textContent = '← Previous';
  previous.disabled = data.page === 0;
  previous.addEventListener('click', () => reload(data.page - 1));

  const next = document.createElement('button');
  next.textContent = 'Next →';
  next.disabled = data.page >= lastPage;
  next.addEventListener('click', () => reload(data.page + 1));

  const label = document.createElement('span');
  label.textContent = `Page ${data.page + 1} of ${lastPage + 1}`;

  pager.append(previous, label, next);
  card.append(pager);
  container.append(card);

  return `${data.total_rows.toLocaleString()} rows`;
}
