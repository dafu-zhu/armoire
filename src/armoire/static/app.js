import { initTree } from './tree.js';
import { initDivider } from './divider.js';
import { initFilter } from './filter.js';
import { renderPreview } from './preview.js';
import { encodeHashPath } from './format.js';
import { renderRoadmap } from './roadmap.js';
import { refreshHabitStates, renderCategories } from './categories.js';
import { categoryOrder } from './palette.js';
import { openPanel, closePanel } from './panel.js';
import { mountRegistryButton } from './registry.js';
import { initNativeOpen } from './opener.js';
import { writeStatus } from './status.js';

const content = document.getElementById('content');
const breadcrumb = document.getElementById('breadcrumb');
// The span, not the footer: every write below is `status.textContent = …`,
// which replaces all children. The footer also holds the registry button
// (registry.js), and a textContent write on the footer would delete it on the
// next navigation. The message owns the span; the footer owns the row.
const status = document.getElementById('status-text');
const nativeOpen = initNativeOpen(document.getElementById('open-native'), status);

const BROWSE = 'browse';
const PROJECT = 'project';
const HEADER_COLLAPSED_KEY = 'armoire.headerCollapsed';

const roadmap = document.getElementById('roadmap');
const canvas = document.getElementById('roadmap-canvas');
const roadmapMessage = document.getElementById('roadmap-message');
const categories = document.getElementById('categories');
const panel = document.getElementById('project-panel');

let roadmapView = null;
let roadmapListeners = null;

// Set once, from initTree's own first fetch (see tree.ready.then below) --
// never refetched per navigation.
let rootLabel = null;
let hasRegistry = false;
// The absolute path to this folder's registry.toml, or null when armoire has
// no usable store for it. Set once, at boot, from the root tree payload.
let registryPath = null;
// The pending single-click navigation for the root crumb, if any. Module
// scope, not local to renderBreadcrumb: a stale timer from a crumb that has
// since been replaced (the user navigated elsewhere before it fired) must
// still be reachable to cancel, or it goes off later and yanks the URL back
// to the root listing out of nowhere.
let rootClickTimer = null;
// Comfortably above the gap between the two clicks of a genuine double
// click (Playwright's included), so the second click's dblclick always has
// a live timer left to cancel; short enough that a real single click still
// feels immediate.
const ROOT_CLICK_DELAY = 250;

function displayRoot(path) {
  // Forward slashes on every platform. Display only -- resolution stays
  // pathlib's job behind resolve_in_root, and this string is never sent back.
  return String(path).replace(/\\/g, '/');
}

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

function renderBreadcrumb(path) {
  breadcrumb.replaceChildren();
  // Any single-click navigation still pending from a previous crumb is
  // already cancelled by showRoute (see its own comment) before this ever
  // runs -- rootClickTimer is guaranteed null here.
  const rootLink = document.createElement('a');
  rootLink.href = `#/${BROWSE}/`;
  rootLink.setAttribute('data-root', '');
  rootLink.textContent = rootLabel || 'armoire';
  rootLink.title = hasRegistry
    ? // "the roadmap" undersells it: a registry that exists but fails to
      // parse also reports hasRegistry true (see dashboard.has_roadmap),
      // and double-clicking there lands on that parse error, not a graph.
      'Click for the root listing, double-click for the roadmap (or its error, if the registry does not parse)'
    : 'Click for the root listing. This folder has no roadmap.';
  // One crumb, not a trail: "D:" and "GitHub" name places outside the served
  // root that armoire cannot show, so they must not look clickable.
  //
  // Both listeners preventDefault unconditionally: a double click fires
  // click, click, dblclick on the same target, so a click handler that
  // navigates immediately would let the first click's own hashchange
  // re-render (and replace) this element out from under the click/dblclick
  // pair that follows. Deferring the single-click navigation instead keeps
  // this element -- and its listeners -- alive for the whole gesture, so
  // dblclick can always find and cancel it.
  rootLink.addEventListener('click', (event) => {
    event.preventDefault();
    if (rootClickTimer) return; // second click of a double click; dblclick decides
    rootClickTimer = window.setTimeout(() => {
      rootClickTimer = null;
      window.location.hash = `/${BROWSE}/`;
    }, ROOT_CLICK_DELAY);
  });
  rootLink.addEventListener('dblclick', (event) => {
    event.preventDefault();
    if (rootClickTimer) {
      window.clearTimeout(rootClickTimer);
      rootClickTimer = null;
    }
    if (hasRegistry) window.location.hash = '/';
  });
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

// The box is always an error: a stub or empty registry is not a failure, and
// takes the same exit as no registry at all -- back to the file browser,
// rather than a message rendered in the roadmap panel. The class used to be a
// parameter, with 'error' the only value any caller ever passed.
//
// #roadmap-message is the only child of #roadmap this module writes, and
// replaceChildren is the only way it writes to it. Appending straight to
// #roadmap meant nothing ever removed a box: they stacked one per visit, and a
// stale error card survived underneath a later successful render.
//
// #categories gets the same treatment as the canvas, and for the same
// reason: both error exits below (the fetch's own catch, and data.error)
// return without ever reaching renderCategories, which is the only other
// place anything writes to #categories. Without this, a category column
// populated by an earlier successful visit would sit, stale, beside an error
// card that says the fetch itself just failed. Emptied, it is also hidden --
// a bordered 240px box with nothing in it is not a column.
function showRoadmapError(message) {
  canvas.replaceChildren();
  categories.replaceChildren();
  categories.hidden = true;
  const box = document.createElement('div');
  box.className = 'error';
  box.textContent = message;
  roadmapMessage.replaceChildren(box);
  // A registry that does not parse is the one screen where the file most
  // needs opening: the message names the line, and the fix is one click and
  // three seconds away. `box.textContent` above created a text node; append
  // adds the button as its sibling rather than replacing it.
  //
  // showRoadmapError's other caller is the /api/projects fetch's own catch
  // (a network error, not a parse error), so the button can also appear for
  // a failure the registry did not cause. Harmless and not worth a branch
  // just to hide it there -- accepted.
  mountRegistryButton(box, registryPath);
}

function clearRoadmapMessage() {
  roadmapMessage.replaceChildren();
}

async function showRoadmap() {
  // Commit to the roadmap before the fetch, not after: /api/projects walks
  // git across every declared path -- seconds on a large folder -- and
  // showing the file browser meanwhile reads as opening on the wrong screen.
  document.getElementById('tree').hidden = true;
  document.getElementById('divider').hidden = true;
  document.getElementById('main').hidden = true;
  roadmap.hidden = false;
  // #categories is unhidden below, once renderCategories reports it has
  // something to show. A fully connected graph isolates nothing, and an empty
  // bordered box would then take 240px off the canvas for no content.
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
  // Every visit re-runs this against the same persistent #roadmap-canvas
  // element. Without aborting the previous run's listeners they accumulate
  // for the lifetime of the page.
  if (roadmapListeners) roadmapListeners.abort();
  roadmapListeners = new AbortController();
  // Projects that participate in no edge that will actually be drawn have no
  // place in the graph -- they belong in the category column instead (see
  // categories.js). Filtering here, before renderRoadmap ever sees them,
  // keeps that one job in roadmap.js and this one in app.js.
  const connected = { ...data, projects: data.projects.filter((p) => !p.isolated) };
  // One order map over the *whole* payload, shared by both renderers, so a
  // category that appears on both sides of the split gets the same colour on
  // both. See palette.js.
  const order = categoryOrder(data.projects);
  // Shared by both renderers (the roadmap graph and the category column): a
  // single click opens the quick-look panel in place, a double click hands
  // off to the same browse view the file tree uses -- no bespoke project
  // page any more. `project.paths[0]` is always present: the registry
  // parser refuses an empty `paths` list (projects.py).
  const onOpenFolder = (project) => {
    closePanel(panel);
    navigate(project.paths[0]);
  };
  const onStatusChange = (name, nextStatus, conditionalNote) => {
    const changed = data.projects.find((project) => project.name === name);
    if (changed) {
      changed.status = nextStatus;
      if (conditionalNote !== undefined) changed.conditional_note = conditionalNote;
    }
    refreshHabitStates(categories, data);
  };
  const onSelect = (project) => openPanel(panel, project, onOpenFolder, {
    onSaveConditionalNote: async (note) => {
      const saved = await writeStatus(project.name, 'conditional-done', undefined, note);
      if (saved) {
        project.conditional_note = note;
        if (project.status === 'conditional-done') {
          onStatusChange(project.name, project.status, note);
        }
        onSelect(project);
      }
      return saved;
    },
  });
  const onRequestConditionalDone = (project, commit) => {
    const preview = { ...project, status: 'conditional-done' };
    openPanel(panel, preview, onOpenFolder, {
      editConditionalNote: true,
      onCancelConditionalNote: () => onSelect(project),
      onSaveConditionalNote: async (note) => {
        const saved = await commit(note);
        if (saved) onSelect(project);
        return saved;
      },
      onMarkFullyDone: async () => {
        const saved = await commit(undefined, 'done');
        if (saved) onSelect(project);
        return saved;
      },
    });
  };
  const callbacks = { onSelect, onOpenFolder, onStatusChange, onRequestConditionalDone };
  roadmapView = renderRoadmap(canvas, connected, callbacks, roadmapListeners.signal, order);
  categories.hidden = renderCategories(categories, data, callbacks, order) === 0;
  document.getElementById('layout-reset').onclick = () => roadmapView.reset();
  document.getElementById('zoom-in').onclick = () => roadmapView.zoomBy(1.2);
  document.getElementById('zoom-out').onclick = () => roadmapView.zoomBy(1 / 1.2);
  const issues = (data.issues || []).length;
  status.textContent = issues
    ? `${data.projects.length} projects · ${issues} issue${issues === 1 ? '' : 's'}`
    : `${data.projects.length} projects`;
}

function hideRoadmap() {
  roadmap.hidden = true;
  categories.hidden = true;
  // #project-panel is a sibling of #roadmap/#categories, not scoped inside
  // either -- without this, leaving the roadmap by any route other than the
  // panel's own "Open project files" button (a typed URL, the filter, a
  // tree click) would leave it sitting open over the file browser.
  closePanel(panel);
  document.getElementById('tree').hidden = false;
  document.getElementById('divider').hidden = false;
  document.getElementById('main').hidden = false;
}

function initHeaderToggle(button) {
  const setCollapsed = (collapsed) => {
    document.body.classList.toggle('header-collapsed', collapsed);
    button.setAttribute('aria-expanded', String(!collapsed));
    button.setAttribute('aria-label', collapsed ? 'Show header' : 'Hide header');
    button.textContent = collapsed ? 'v' : '^';
    window.localStorage.setItem(HEADER_COLLAPSED_KEY, collapsed ? '1' : '0');
  };

  setCollapsed(window.localStorage.getItem(HEADER_COLLAPSED_KEY) === '1');
  button.addEventListener('click', () => {
    setCollapsed(!document.body.classList.contains('header-collapsed'));
  });
}

async function showRoute(route) {
  // A pending single-click navigation belongs to whatever crumb armed it.
  // Clearing it only inside renderBreadcrumb misses the 'home' route below,
  // which never calls renderBreadcrumb at all: reaching the roadmap by any
  // means other than the crumb's own dblclick (browser Back onto a prior
  // roadmap entry, for instance) would otherwise leave the timer alive to
  // fire later and silently pull the user back off the page they just
  // reached. Every route change cancels it, unconditionally.
  if (rootClickTimer) {
    window.clearTimeout(rootClickTimer);
    rootClickTimer = null;
  }
  nativeOpen.setPath(route.kind === 'browse' ? route.path : '');
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
    // No page of its own any more -- a bookmarked #/project/<name> resolves
    // the name against the same payload the roadmap uses and hands off to
    // the folder's normal browse view. Nothing in this app writes this route
    // any more (see onOpenFolder in showRoadmap); it exists only so an old
    // link still lands somewhere useful instead of a dead page.
    renderBreadcrumb('');
    status.textContent = 'Loading…';
    try {
      const data = await (await fetch('/api/projects')).json();
      if (data.error) throw new Error(data.error);
      const match = (data.projects || []).find((p) => p.name === route.name);
      if (!match) throw new Error(`no such project: ${route.name}`);
      window.location.hash = `/${BROWSE}/${encodeHashPath(match.paths[0])}`;
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
initHeaderToggle(document.getElementById('header-toggle'));

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
  .then((rootMeta) => {
    rootLabel = displayRoot(rootMeta.root);
    hasRegistry = rootMeta.hasRegistry;
    registryPath = rootMeta.registry;
    // The footer, not the roadmap: a folder with only a stub registry never
    // reaches the roadmap at all (see showRoadmap's fallback below), and the
    // registry is exactly what it needs to edit to get there.
    mountRegistryButton(document.getElementById('status'), registryPath);
    const rootNameEl = document.getElementById('root-name');
    rootNameEl.textContent = rootLabel;
    // A single click, unlike the breadcrumb root crumb's click/dblclick
    // split: this label has only one destination (the roadmap), so there is
    // nothing for a second click to disambiguate.
    rootNameEl.tabIndex = 0;
    rootNameEl.setAttribute('role', 'button');
    rootNameEl.title = 'Go to the roadmap';
    const goToRoadmap = () => {
      window.location.hash = '/';
    };
    rootNameEl.addEventListener('click', goToRoadmap);
    rootNameEl.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        goToRoadmap();
      }
    });
    initDivider(document.getElementById('divider'), document.getElementById('tree'), rootLabel);
    const route = currentRoute();
    if (route.kind === 'unknown') {
      window.location.hash = `/${BROWSE}/${encodeHashPath(route.path)}`;
      return;
    }
    showRoute(route);
  })
  .catch(showError);
