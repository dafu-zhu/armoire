import { initTree } from './tree.js';
import { initFilter } from './filter.js';
import { renderPreview } from './preview.js';
import { encodeHashPath } from './format.js';
import { renderRoadmap } from './roadmap.js';
import { initRail } from './rail.js';
import { renderProject } from './project.js';

const content = document.getElementById('content');
const breadcrumb = document.getElementById('breadcrumb');
const status = document.getElementById('status');

const BROWSE = 'browse';
const PROJECT = 'project';

const roadmap = document.getElementById('roadmap');
const canvas = document.getElementById('roadmap-canvas');
const roadmapMessage = document.getElementById('roadmap-message');
const body = document.getElementById('body');

let roadmapView = null;
let roadmapListeners = null;

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

// className is always 'error' here: a stub or empty registry is not a
// failure, and takes the same exit as no registry at all -- back to the
// file browser, rather than a message rendered in the roadmap panel.
//
// #roadmap-message is the only child of #roadmap this module writes, and
// replaceChildren is the only way it writes to it. Appending straight to
// #roadmap meant nothing ever removed a box: they stacked one per visit, and a
// stale error card survived underneath a later successful render.
function showRoadmapMessage(message, className) {
  canvas.replaceChildren();
  const box = document.createElement('div');
  box.className = className;
  box.textContent = message;
  roadmapMessage.replaceChildren(box);
}

function clearRoadmapMessage() {
  roadmapMessage.replaceChildren();
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
  // Clear on entry, not on success: every path out of here either renders a
  // graph or writes exactly one message, so the previous visit's box never
  // outlives the visit that wrote it.
  clearRoadmapMessage();
  status.textContent = 'Loading roadmap…';

  let data;
  try {
    data = await (await fetch('/api/projects')).json();
  } catch (error) {
    showRoadmapError(String(error.message || error));
    return;
  }

  if (data.error) {
    showRoadmapError(data.error);
    return;
  }
  if (data.registry === false || !data.projects.length) {
    // A stub registry is the normal state for a folder nobody has described
    // yet, so "no projects" means the same thing "no file" used to: there is
    // no roadmap here, hand back to the browser.
    hideRoadmap();
    window.location.hash = `/${BROWSE}/`;
    return;
  }
  // Every visit re-runs this against the same persistent #roadmap-canvas and
  // #rail-toggle elements. Without aborting the previous run's listeners they
  // accumulate for the lifetime of the page.
  if (roadmapListeners) roadmapListeners.abort();
  roadmapListeners = new AbortController();
  roadmapView = renderRoadmap(canvas, data, navigateProject, roadmapListeners.signal);
  initRail(
    document.getElementById('rail-toggle'),
    document.getElementById('rail'),
    data,
    navigateProject,
    roadmapListeners.signal,
  );
  document.getElementById('layout-reset').onclick = () => roadmapView.reset();
  document.getElementById('zoom-in').onclick = () => roadmapView.zoomBy(1.2);
  document.getElementById('zoom-out').onclick = () => roadmapView.zoomBy(1 / 1.2);
  status.textContent = `${data.projects.length} projects`;
}

function hideRoadmap() {
  roadmap.hidden = true;
  document.getElementById('tree').hidden = false;
  document.getElementById('main').hidden = false;
}

async function showRoute(route) {
  if (route.kind === 'home') {
    try {
      await showRoadmap();
    } catch (error) {
      // Unawaited, a throw inside renderRoadmap left the screen on
      // "Loading roadmap…" with no error card and an unhandled rejection.
      // Same destination as a failed fetch: the user sees what went wrong.
      showRoadmapError(String(error.message || error));
    }
    return;
  }
  hideRoadmap();
  if (route.kind === 'project') {
    renderBreadcrumb('');
    status.textContent = 'Loading…';
    try {
      status.textContent = await renderProject(content, route.name, navigate);
    } catch (error) {
      showError(error);
    }
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
