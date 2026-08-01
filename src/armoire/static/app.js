import { initTree } from './tree.js';
import { initFilter } from './filter.js';
import { renderPreview } from './preview.js';
import { encodeHashPath } from './format.js';

const content = document.getElementById('content');
const breadcrumb = document.getElementById('breadcrumb');
const status = document.getElementById('status');

function currentPath() {
  const raw = window.location.hash.replace(/^#\/?/, '');
  // decodeURIComponent throws on a malformed percent-escape -- e.g. a literal
  // "%" that was never encoded. format.js's encodeHashPath is the single
  // write path every producer of location.hash is expected to route
  // through, so a well-formed hash always round-trips; a malformed one
  // (hand-typed, hand-edited, or from a write site that skipped it) must
  // surface as a visible error rather than an uncaught exception that
  // freezes the page.
  return raw
    .split('/')
    .map((segment) => decodeURIComponent(segment))
    .join('/');
}

export function navigate(path) {
  window.location.hash = `/${encodeHashPath(path)}`;
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
    link.href = `#/${encodeHashPath(accumulated)}`;
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
  let path;
  try {
    path = currentPath();
  } catch (error) {
    // Not inside a promise chain, so an uncaught decode error here would be
    // an unhandled exception with no error card -- the page just freezes.
    showError(error);
    return;
  }
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
