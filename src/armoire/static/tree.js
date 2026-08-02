// Lazy directory tree. One fetch per expand — the full walk never happens here.

const cache = new Map();

async function fetchDir(path) {
  if (cache.has(path)) return cache.get(path);
  const response = await fetch(`/api/tree?path=${encodeURIComponent(path)}`);
  if (!response.ok) throw new Error(`tree ${response.status}`);
  const data = await response.json();
  cache.set(path, data);
  return data;
}

function join(parent, name) {
  return parent ? `${parent}/${name}` : name;
}

function makeRow(label, caret) {
  const row = document.createElement('div');
  row.className = 'row';
  const arrow = document.createElement('span');
  arrow.className = 'caret';
  arrow.textContent = caret;
  const text = document.createElement('span');
  text.textContent = label;
  row.append(arrow, text);
  return { row, arrow };
}

export function initTree(container, onSelect) {
  let selected = null;
  // Maps a directory row to a function that resolves once its children exist.
  // revealPath awaits these; without that it would query for grandchildren
  // before the parent's fetch had returned.
  const expanders = new WeakMap();
  // Populated from the root directory's own fetch below -- every /api/tree
  // response carries the same `root`/`has_registry`, so there is no reason
  // for app.js to make a second, redundant request for them.
  let rootMeta = { root: null, hasRegistry: false };

  function select(row) {
    if (selected) selected.removeAttribute('aria-current');
    selected = row;
    row.setAttribute('aria-current', 'true');
  }

  async function buildList(path) {
    const data = await fetchDir(path);
    const { dirs, files } = data;
    if (path === '') rootMeta = { root: data.root, hasRegistry: data.has_registry };
    const list = document.createElement('ul');

    for (const dir of dirs) {
      const full = join(path, dir.name);
      const item = document.createElement('li');
      const { row, arrow } = makeRow(dir.name, '▸');
      row.dataset.path = full;

      let children = null;
      let building = null;

      async function expand() {
        if (!building) {
          building = buildList(full).then((list) => {
            children = list;
            item.append(list);
          });
        }
        await building;
        children.hidden = false;
        arrow.textContent = '▾';
      }

      row.addEventListener('click', () => {
        if (children && !children.hidden) {
          children.hidden = true;
          arrow.textContent = '▸';
        } else {
          expand();
        }
        select(row);
        onSelect(full);
      });

      expanders.set(row, expand);
      item.append(row);
      list.append(item);
    }

    for (const file of files) {
      const full = join(path, file.name);
      const item = document.createElement('li');
      const { row } = makeRow(file.name, '');
      row.dataset.path = full;
      row.addEventListener('click', () => {
        select(row);
        onSelect(full);
      });
      item.append(row);
      list.append(item);
    }

    return list;
  }

  async function revealPath(path) {
    const parts = path.split('/').filter(Boolean);
    let current = '';
    for (const part of parts) {
      current = join(current, part);
      const row = container.querySelector(`[data-path="${CSS.escape(current)}"]`);
      if (!row) return;
      const expand = expanders.get(row);
      // Directories have an expander and must finish before the next lookup.
      // Files do not, and are the last part of the path anyway.
      if (expand) await expand();
      select(row);
      row.scrollIntoView({ block: 'nearest' });
    }
  }

  const ready = buildList('').then((list) => {
    container.replaceChildren(list);
    return rootMeta;
  });

  return { ready, revealPath };
}
