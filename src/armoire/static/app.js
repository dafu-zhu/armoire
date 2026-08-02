import { initTree } from './tree.js';
import { initFilter } from './filter.js';
import { renderPreview } from './preview.js';
import { encodeHashPath } from './format.js';

const content = document.getElementById('content');
const breadcrumb = document.getElementById('breadcrumb');
const status = document.getElementById('status');

const BROWSE = 'browse';
const PROJECT = 'project';

function decodeSegments(raw) {
  return raw
    .split('/')
    .map((segment) => decodeURIComponent(segment))
    .join('/');
}

// Everything that is not a file lives behind a reserved first segment, and
// every file lives behind `browse`. That removes the collision entirely: a
// folder actually named "browse" is #/browse/browse.
function currentRoute() {
  const raw = window.location.hash.replace(/^#\/?/, '');
  if (raw === '') return { kind: 'home' };
  const slash = raw.indexOf('/');
  const head = slash === -1 ? raw : raw.slice(0, slash);
  const rest = slash === -1 ? '' : raw.slice(slash + 1);
  if (head === PROJECT) return { kind: 'project', name: decodeURIComponent(rest) };
  if (head === BROWSE) return { kind: 'browse', path: decodeSegments(rest) };
  return { kind: 'unknown', raw };
}

export function navigate(path) {
  window.location.hash = `/${BROWSE}/${encodeHashPath(path)}`;
}

export function navigateProject(name) {
  window.location.hash = `/${PROJECT}/${encodeURIComponent(name)}`;
}

function renderBreadcrumb(path) {
  breadcrumb.replaceChildren();
  const rootLink = document.createElement('a');
  rootLink.href = `#/${BROWSE}/`;
  rootLink.textContent = document.getElementById('root-name').textContent;
  breadcrumb.append(rootLink);

  let accumulated = '';
  for (const part of path.split('/').filter(Boolean)) {
    accumulated = accumulated ? `${accumulated}/${part}` : part;
    breadcrumb.append(document.createTextNode(' / '));
    const link = document.createElement('a');
    link.href = `#/${BROWSE}/${encodeHashPath(accumulated)}`;
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

async function showRoute(route) {
  if (route.kind === 'project') {
    status.textContent = 'Loading…';
    // Task 8 replaces this with the real detail view.
    content.replaceChildren();
    return;
  }
  const path = route.kind === 'browse' ? route.path : '';
  renderBreadcrumb(path);
  status.textContent = 'Loading…';
  try {
    const meta = await renderPreview(content, path);
    status.textContent = meta || path || '/';
  } catch (error) {
    showError(error);
  }
  tree.revealPath(path);
}

const tree = initTree(document.getElementById('tree'), navigate);
initFilter(
  document.getElementById('filter'),
  document.getElementById('filter-results'),
  navigate,
);

window.addEventListener('hashchange', () => {
  let route;
  try {
    route = currentRoute();
  } catch (error) {
    showError(error);
    return;
  }
  if (route.kind === 'home') {
    window.location.hash = `/${BROWSE}/`;
    return;
  }
  showRoute(route);
});

tree.ready
  .then(() => {
    const route = currentRoute();
    if (route.kind === 'home') {
      window.location.hash = `/${BROWSE}/`;
      return;
    }
    showRoute(route);
  })
  .catch(showError);
