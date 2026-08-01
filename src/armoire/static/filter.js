// Subsequence match over the flat index, ranked by how tight the match is.

function score(path, query) {
  const haystack = path.toLowerCase();
  let index = -1;
  let first = -1;
  let last = -1;
  for (const char of query) {
    index = haystack.indexOf(char, index + 1);
    if (index === -1) return null;
    if (first === -1) first = index;
    last = index;
  }
  // Tighter spans and matches nearer the filename rank higher.
  const span = last - first;
  const tailBonus = haystack.length - last;
  return span * 4 + tailBonus;
}

export function initFilter(input, results, onPick) {
  let paths = [];
  let matches = [];
  let cursor = 0;

  fetch('/api/index')
    .then((r) => r.json())
    .then((data) => {
      paths = data.paths;
      input.placeholder = `Filter ${paths.length} files…`;
    });

  function close() {
    results.hidden = true;
    matches = [];
    cursor = 0;
  }

  function render() {
    results.replaceChildren();
    matches.forEach((path, i) => {
      const cut = path.lastIndexOf('/');
      const item = document.createElement('li');
      if (cut !== -1) {
        const dir = document.createElement('span');
        dir.className = 'dir';
        dir.textContent = `${path.slice(0, cut + 1)}`;
        item.append(dir);
      }
      item.append(document.createTextNode(path.slice(cut + 1)));
      item.setAttribute('aria-selected', String(i === cursor));
      item.addEventListener('mousedown', (event) => {
        event.preventDefault();
        onPick(path);
        input.value = '';
        close();
      });
      results.append(item);
    });
    results.hidden = matches.length === 0;
  }

  input.addEventListener('input', () => {
    const query = input.value.trim().toLowerCase();
    if (!query) return close();
    matches = paths
      .map((path) => ({ path, rank: score(path, query) }))
      .filter((entry) => entry.rank !== null)
      .sort((a, b) => a.rank - b.rank)
      .slice(0, 50)
      .map((entry) => entry.path);
    cursor = 0;
    render();
  });

  input.addEventListener('keydown', (event) => {
    if (results.hidden) return;
    if (event.key === 'ArrowDown') {
      cursor = Math.min(cursor + 1, matches.length - 1);
      render();
      event.preventDefault();
    } else if (event.key === 'ArrowUp') {
      cursor = Math.max(cursor - 1, 0);
      render();
      event.preventDefault();
    } else if (event.key === 'Enter' && matches[cursor]) {
      onPick(matches[cursor]);
      input.value = '';
      close();
      event.preventDefault();
    } else if (event.key === 'Escape') {
      close();
    }
  });

  input.addEventListener('blur', close);
}
