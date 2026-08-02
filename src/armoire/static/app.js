import { initTree } from './tree.js';
import { initFilter } from './filter.js';
import { renderPreview } from './preview.js';
import { encodeHashPath } from './format.js';
import { renderRoadmap } from './roadmap.js';

const content = document.getElementById('content');
const breadcrumb = document.getElementById('breadcrumb');
const status = document.getElementById('status');

const BROWSE = 'browse';
const PROJECT = 'project';

const roadmap = document.getElementById('roadmap');
const canvas = document.getElementById('roadmap-canvas');
const body = document.getElementById('body');

let roadmapView = null;

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
  // A hash from before file browsing moved under #/browse/ -- e.g. a bookmark
  // made under Phase 1's #/<path> scheme. It is a browse path missing its
  // prefix, so decode it the same way a browse route would be: doing that
  // here, rather than at the redirect call site, means an uncaught decode
  // error still surfaces through the same try/catch that already wraps every
  // currentRoute() call instead of escaping from inside a redirect.
  return { kind: 'unknown', path: decodeSegments(raw) };
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

// className is 'error' for a genuine failure (fetch/network, malformed
// registry) or 'empty' for a valid-but-empty registry, which is not a
// failure and should not read like one. 'empty' reuses the same neutral
// style preview.js already uses for "no preview for this file".
function showRoadmapMessage(message, className) {
  canvas.replaceChildren();
  const box = document.createElement('div');
  box.className = className;
  box.textContent = message;
  roadmap.append(box);
}

function showRoadmapError(message) {
  showRoadmapMessage(message, 'error');
}

async function showRoadmap() {
  // Commit to the roadmap before the fetch, not after: /api/projects walks
  // git across every declared path -- seconds on a large folder -- and
  // showing the file browser meanwhile reads as opening on the wrong screen.
  document.getElementById('tree').hidden = true;
  document.getElementById('main').hidden = true;
  roadmap.hidden = false;
  status.textContent = 'Loading roadmap…';

  let data;
  try {
    data = await (await fetch('/api/projects')).json();
  } catch (error) {
    showRoadmapError(String(error.message || error));
    return;
  }

  if (data.registry === false) {
    // No registry: this folder has no roadmap, so hand back to the browser.
    hideRoadmap();
    window.location.hash = `/${BROWSE}/`;
    return;
  }
  if (data.error) {
    showRoadmapError(data.error);
    return;
  }
  if (!data.projects.length) {
    // Zero [[project]] entries is valid TOML and reaches here with neither
    // registry: false nor error -- an empty graph, not a failure.
    showRoadmapMessage('No projects declared in armoire.toml.', 'empty');
    status.textContent = 'no projects';
    return;
  }
  roadmapView = renderRoadmap(canvas, data, navigateProject);
  status.textContent = `${data.projects.length} projects`;
}

function hideRoadmap() {
  roadmap.hidden = true;
  document.getElementById('tree').hidden = false;
  document.getElementById('main').hidden = false;
}

async function showRoute(route) {
  if (route.kind === 'home') {
    showRoadmap();
    return;
  }
  hideRoadmap();
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
  if (route.kind === 'unknown') {
    // A hash from before file browsing moved under #/browse/. It is a browse
    // path missing its prefix, so migrate it rather than rendering the root
    // listing under a stale URL and silently showing unrelated content.
    window.location.hash = `/${BROWSE}/${encodeHashPath(route.path)}`;
    return;
  }
  showRoute(route);
});

tree.ready
  .then(() => {
    const route = currentRoute();
    if (route.kind === 'unknown') {
      window.location.hash = `/${BROWSE}/${encodeHashPath(route.path)}`;
      return;
    }
    showRoute(route);
  })
  .catch(showError);
