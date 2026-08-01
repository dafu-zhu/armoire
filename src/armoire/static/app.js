import { initTree } from './tree.js';
import { initFilter } from './filter.js';
import { renderPreview } from './preview.js';

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

function showError(error) {
  content.replaceChildren();
  const box = document.createElement('div');
  box.className = 'error';
  box.textContent = String(error.message || error);
  content.append(box);
  status.textContent = 'Error';
}

async function show(path) {
  renderBreadcrumb(path);
  status.textContent = 'Loading…';
  try {
    const meta = await renderPreview(content, path);
    status.textContent = meta || path || '/';
  } catch (error) {
    showError(error);
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

tree.ready
  .then(() => {
    const path = currentPath();
    show(path);
    if (path) tree.revealPath(path);
  })
  // A backend error on the initial listing would otherwise leave the tree
  // permanently empty with nothing but an unhandled rejection in the console.
  .catch(showError);
