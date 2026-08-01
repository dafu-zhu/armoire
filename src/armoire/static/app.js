import { initTree } from './tree.js';
import { initFilter } from './filter.js';

const content = document.getElementById('content');
const breadcrumb = document.getElementById('breadcrumb');
const status = document.getElementById('status');

function currentPath() {
  const hash = decodeURIComponent(window.location.hash.replace(/^#\/?/, ''));
  return hash;
}

export function navigate(path) {
  window.location.hash = `/${path}`;
}

function renderBreadcrumb(path) {
  breadcrumb.replaceChildren();
  const rootLink = document.createElement('a');
  rootLink.href = '#/';
  rootLink.textContent = document.getElementById('root-name').textContent;
  breadcrumb.append(rootLink);

  let accumulated = '';
  for (const part of path.split('/').filter(Boolean)) {
    accumulated = accumulated ? `${accumulated}/${part}` : part;
    breadcrumb.append(document.createTextNode(' / '));
    const link = document.createElement('a');
    link.href = `#/${accumulated}`;
    link.textContent = part;
    breadcrumb.append(link);
  }
}

async function show(path) {
  renderBreadcrumb(path);
  status.textContent = 'Loading…';
  try {
    // Deferred (rather than a static top-level import): a static import of a
    // module that doesn't exist fails the whole ES module graph, so nothing
    // in this file — tree, filter, router — would run at all. Task 11 has
    // not created preview.js yet; until it does, this rejects and the
    // catch below reports it, without taking the rest of the page down.
    const { renderPreview } = await import('./preview.js');
    const meta = await renderPreview(content, path);
    status.textContent = meta || path || '/';
  } catch (error) {
    content.replaceChildren();
    const box = document.createElement('div');
    box.className = 'error';
    box.textContent = String(error.message || error);
    content.append(box);
    status.textContent = 'Error';
  }
}

const tree = initTree(document.getElementById('tree'), navigate);
initFilter(
  document.getElementById('filter'),
  document.getElementById('filter-results'),
  navigate,
);

window.addEventListener('hashchange', () => {
  const path = currentPath();
  show(path);
  tree.revealPath(path);
});

tree.ready.then(() => {
  const path = currentPath();
  show(path);
  if (path) tree.revealPath(path);
});
