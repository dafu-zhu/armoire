// The roadmap. dagre assigns ranks and positions; the SVG is rendered here so
// click targets, drag and styling stay under our control -- mermaid would emit
// a static picture we would then have to fight.

import { nextStatus, glyphFor, setStatus } from './status.js';

const NODE_W = 168;
const CATEGORIES = 6;
const NODE_PAD_X = 12;
const TITLE_Y = 24;
const LINE_H = 15;
const NODE_MIN_H = 40;

// SVG <text> does not wrap. Measure in the live SVG rather than guessing from
// character counts: font metrics are not knowable ahead of time, and the
// previous fixed-height node let every long note render outside its own box.
//
// The probe must be styled exactly like the real .node-sub it stands in for,
// or every wrap decision is computed against the wrong font. `.node .node-sub`
// (app.css) is a descendant selector requiring a `.node` ancestor; a probe
// appended directly to `canvas` has no such ancestor and falls back to the
// body's font-size instead. Nesting the probe inside a throwaway
// `.node`-classed host makes the same CSS rule apply to both the probe and
// the real subtitle, so they can never drift apart even if that rule's
// font-size later changes -- a hardcoded font-size here would have to be
// kept in sync with the CSS by hand instead.
function wrapLines(canvas, text, maxWidth) {
  const probeHost = svgEl('g', { class: 'node', visibility: 'hidden' });
  const probe = svgEl('text', { class: 'node-sub' });
  probeHost.append(probe);
  canvas.append(probeHost);
  const lines = [];
  let current = '';
  const push = () => { if (current) lines.push(current); current = ''; };
  for (const word of String(text).split(/\s+/).filter(Boolean)) {
    const candidate = current ? `${current} ${word}` : word;
    probe.textContent = candidate;
    if (probe.getComputedTextLength() <= maxWidth) { current = candidate; continue; }
    push();
    probe.textContent = word;
    if (probe.getComputedTextLength() <= maxWidth) { current = word; continue; }
    // A single word wider than the box -- a long path or an unbroken token.
    // Break it rather than let it escape the rect.
    let chunk = '';
    for (const ch of word) {
      probe.textContent = chunk + ch;
      if (probe.getComputedTextLength() > maxWidth && chunk) { lines.push(chunk); chunk = ch; }
      else chunk += ch;
    }
    current = chunk;
  }
  push();
  probeHost.remove();
  return lines;
}

function nodeHeight(lineCount) {
  return Math.max(NODE_MIN_H, TITLE_Y + 6 + lineCount * LINE_H + 8);
}

// The one place a project's subtitle is decided. A fixed-height node used to
// force a choice between `due` and `note` (whichever `||` picked); nodes now
// grow to fit, so both render -- the due date first, unwrapped (an ISO date
// is short and fixed-format, so it needs no measurement), the note wrapped
// beneath it. Task 7's "done" collapse needs to suppress both the due line
// and the note at once for a done project; add that as an early return here
// (e.g. `if (project.status === 'done') return { dueLine: null, noteLines: [] };`)
// and every caller -- height computation and rendering both read this same
// result -- picks it up for free.
function buildSubtitle(canvas, project) {
  // A done project's subtitle collapses to nothing, in both the height pass
  // and the render pass, because both read this one return value -- see the
  // comment above this function. This reads `project.status` (the payload's
  // status as it was when renderRoadmap was called), never the live
  // `statuses` Map a click mutates: collapsing mid-gesture would re-lay out
  // the whole graph and move every node under the pointer, so the collapse
  // is deliberately one render behind a click. Do not "fix" this into a
  // reflow.
  if (project.status === 'done') return { dueLine: null, noteLines: [] };
  const dueLine = project.due ? `Due ${project.due}` : null;
  const noteLines = project.note ? wrapLines(canvas, project.note, NODE_W - NODE_PAD_X * 2) : [];
  return { dueLine, noteLines };
}

function subtitleLineCount(subtitle) {
  return (subtitle.dueLine ? 1 : 0) + subtitle.noteLines.length;
}

function storageKey(root) {
  return `armoire:layout:${root}`;
}

function loadSaved(root) {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(storageKey(root)) || '{}');
    // JSON.parse('null') succeeds and yields null, which Object.entries
    // rejects -- the catch below never sees it.
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    // A corrupt entry must not take the roadmap down with it.
    return {};
  }
}

function save(root, positions) {
  const plain = {};
  for (const [name, pos] of positions) plain[name] = { x: pos.x, y: pos.y };
  try {
    window.localStorage.setItem(storageKey(root), JSON.stringify(plain));
  } catch {
    // Quota or a privacy mode that blocks storage. Dragging still works for
    // this session; it just will not persist.
  }
}

function categoryClass(category, order) {
  if (!category) return 'cat-5';
  if (!order.has(category)) order.set(category, order.size % (CATEGORIES - 1));
  return `cat-${order.get(category)}`;
}

function svgEl(name, attrs = {}) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', name);
  for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
  return el;
}

function layout(projects, heights, known) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', align: 'UL', nodesep: 28, ranksep: 72, marginx: 24, marginy: 24 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const project of projects) {
    g.setNode(project.name, { width: NODE_W, height: heights.get(project.name) });
  }
  for (const project of projects) {
    for (const blocker of project.blocked_by) {
      // An unknown blocker is reported as an issue in the rail; drawing an
      // edge to a node that does not exist would throw inside dagre.
      if (known.has(blocker)) g.setEdge(blocker, project.name);
    }
  }
  dagre.layout(g);
  return g;
}

export function renderRoadmap(canvas, data, onOpen, signal) {
  const projects = data.projects || [];
  const order = new Map();
  const positions = new Map();
  const known = new Set(projects.map((p) => p.name));

  canvas.replaceChildren();
  const subtitles = new Map();
  const heights = new Map();
  for (const project of projects) {
    const subtitle = buildSubtitle(canvas, project);
    subtitles.set(project.name, subtitle);
    heights.set(project.name, nodeHeight(subtitleLineCount(subtitle)));
  }
  const g = layout(projects, heights, known);
  const defs = svgEl('defs');
  const marker = svgEl('marker', {
    id: 'arrow', markerWidth: '9', markerHeight: '9',
    refX: '8', refY: '3', orient: 'auto',
  });
  marker.append(svgEl('path', { d: 'M0,0 L8,3 L0,6', fill: 'var(--muted)' }));
  defs.append(marker);
  canvas.append(defs);

  const viewport = svgEl('g', { id: 'viewport' });
  const edgeLayer = svgEl('g');
  const nodeLayer = svgEl('g');
  viewport.append(edgeLayer, nodeLayer);
  canvas.append(viewport);

  for (const id of g.nodes()) positions.set(id, { ...g.node(id) });

  const computed = new Map();
  for (const [name, pos] of positions) computed.set(name, { x: pos.x, y: pos.y });
  const saved = loadSaved(data.root);
  for (const [name, pos] of Object.entries(saved)) {
    if (positions.has(name)) positions.set(name, { ...positions.get(name), ...pos });
  }

  function edgePath(from, to) {
    const a = positions.get(from);
    const b = positions.get(to);
    const midX = (a.x + NODE_W / 2 + (b.x - NODE_W / 2)) / 2;
    return `M${a.x + NODE_W / 2},${a.y} C${midX},${a.y} ${midX},${b.y} ${b.x - NODE_W / 2},${b.y}`;
  }

  const edges = [];
  for (const e of g.edges()) {
    const path = svgEl('path', {
      class: 'edge', d: edgePath(e.v, e.w), 'marker-end': 'url(#arrow)',
    });
    edgeLayer.append(path);
    edges.push({ from: e.v, to: e.w, path });
  }

  function redrawEdges() {
    for (const edge of edges) edge.path.setAttribute('d', edgePath(edge.from, edge.to));
  }

  const statuses = new Map(projects.map((p) => [p.name, p.status]));

  function isBlocked(project) {
    // Blocked means "waiting on something unfinished", not "has a blocker".
    // A done project is waiting on nothing by definition.
    if (statuses.get(project.name) === 'done') return false;
    return project.blocked_by.some((b) => known.has(b) && statuses.get(b) !== 'done');
  }

  // Match each project against the issues rather than splitting the issue on
  // ":", which loses any project whose own name contains one. This is the same
  // test the per-node tooltip uses; two methods for one thing disagreed.
  const flagged = new Set(
    projects
      .filter((project) => (data.issues || []).some((issue) => issue.startsWith(`${project.name}:`)))
      .map((project) => project.name),
  );

  // `dragging` itself cannot be the click guard's signal: pointerup resets it
  // to null before the native mouseup/click pair that follows in the same
  // synchronous dispatch, so a click handler reading `dragging` would always
  // see it already cleared. suppressClick is recomputed on every pointerup,
  // read once by the click that immediately follows in the same gesture.
  let dragging = null;
  let suppressClick = false;
  for (const project of projects) {
    const pos = positions.get(project.name);
    if (!pos) continue;
    const height = heights.get(project.name);
    const group = svgEl('g', {
      class: `node ${categoryClass(project.category, order)} status-${statuses.get(project.name)}${
        isBlocked(project) ? ' blocked' : ''
      }`,
      'data-name': project.name,
      transform: `translate(${pos.x - NODE_W / 2},${pos.y - height / 2})`,
      tabindex: '0',
      role: 'button',
    });
    group.append(svgEl('rect', { width: NODE_W, height }));

    const title = svgEl('text', { x: NODE_PAD_X, y: TITLE_Y });
    title.textContent = project.name;
    group.append(title);

    const subtitle = subtitles.get(project.name);
    let subY = TITLE_Y + 18;
    if (subtitle.dueLine) {
      const due = svgEl('text', { x: NODE_PAD_X, y: subY, class: 'node-due' });
      due.textContent = subtitle.dueLine;
      group.append(due);
      subY += LINE_H;
    }
    if (subtitle.noteLines.length) {
      const sub = svgEl('text', { x: NODE_PAD_X, y: subY, class: 'node-sub' });
      for (const [i, line] of subtitle.noteLines.entries()) {
        const span = svgEl('tspan', { x: NODE_PAD_X, dy: i === 0 ? 0 : LINE_H });
        span.textContent = line;
        sub.append(span);
      }
      group.append(sub);
    }

    if (flagged.has(project.name)) {
      const warn = svgEl('text', {
        x: NODE_W - 12, y: height - 10, class: 'node-warn', 'text-anchor': 'end',
      });
      warn.textContent = '!';
      const reason = svgEl('title');
      reason.textContent = (data.issues || [])
        .filter((issue) => issue.startsWith(`${project.name}:`))
        .join('\n');
      warn.append(reason);
      group.append(warn);
    }

    const chip = svgEl('text', {
      x: NODE_W - NODE_PAD_X, y: TITLE_Y, class: 'status-chip',
      'text-anchor': 'end', tabindex: '0', role: 'button',
    });
    chip.textContent = glyphFor(statuses.get(project.name));
    chip.setAttribute('aria-label', `Status: ${statuses.get(project.name)}. Click to change.`);
    const cycle = async (event) => {
      // The chip lives inside the node group, whose own click handler opens
      // the detail view. Without stopPropagation every status change would
      // also navigate away from the screen showing it.
      event.stopPropagation();
      event.preventDefault();
      const previous = statuses.get(project.name);
      const wanted = nextStatus(previous);
      statuses.set(project.name, wanted);
      applyStatus(project.name);
      try {
        await setStatus(project.name, wanted);
      } catch {
        // The write failed; the screen must not keep claiming it succeeded.
        statuses.set(project.name, previous);
        applyStatus(project.name);
      }
    };
    chip.addEventListener('click', cycle);
    chip.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') cycle(event);
    });
    group.append(chip);

    group.addEventListener('click', () => {
      if (suppressClick) return;
      onOpen(project.name);
    });
    group.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') onOpen(project.name);
    });
    nodeLayer.append(group);
  }

  // Unblocking is transitive through one hop only -- a dependent's class
  // depends on its blockers' statuses, not on the whole chain -- but a
  // change to any one project can still flip any number of others' `blocked`
  // class, so every node is recomputed rather than tracking a dependency
  // graph for it. Seventeen nodes is nothing; do the simple thing.
  function applyStatus(changed) {
    for (const project of projects) {
      const group = nodeLayer.querySelector(`[data-name="${CSS.escape(project.name)}"]`);
      if (!group) continue;
      const status = statuses.get(project.name);
      group.setAttribute(
        'class',
        `node ${categoryClass(project.category, order)} status-${status}${
          isBlocked(project) ? ' blocked' : ''
        }`,
      );
      const chip = group.querySelector('.status-chip');
      if (chip) {
        chip.textContent = glyphFor(status);
        chip.setAttribute('aria-label', `Status: ${status}. Click to change.`);
      }
    }
    for (const edge of edges) {
      edge.path.classList.toggle('from-done', statuses.get(edge.from) === 'done');
    }
  }
  // Called once here, unconditionally, so the initial edge classes (e.g. a
  // project whose payload already carries status "done") are right before
  // any click ever happens -- not just after the first one.
  applyStatus();

  const graph = g.graph();
  // Number.isFinite, not `||`: dagre leaves width at -Infinity for an empty
  // graph, and -Infinity is truthy, so the fallback never fired.
  const width = Number.isFinite(graph.width) && graph.width > 0 ? graph.width : 800;
  const height = Number.isFinite(graph.height) && graph.height > 0 ? graph.height : 400;
  canvas.setAttribute('viewBox', `0 0 ${width} ${height}`);

  let scale = 1;
  let pan = { x: 0, y: 0 };

  function applyViewport() {
    viewport.setAttribute('transform', `translate(${pan.x},${pan.y}) scale(${scale})`);
    const label = document.getElementById('zoom-level');
    if (label) label.textContent = `${Math.round(scale * 100)}%`;
  }

  function place(name) {
    const pos = positions.get(name);
    const group = nodeLayer.querySelector(`[data-name="${CSS.escape(name)}"]`);
    if (group) {
      group.setAttribute(
        'transform',
        `translate(${pos.x - NODE_W / 2},${pos.y - heights.get(name) / 2})`,
      );
    }
  }

  // These four listeners live on `canvas`, which persists across every call
  // to renderRoadmap (app.js re-fetches it once via getElementById and reuses
  // it) -- unlike the per-node listeners above, which are torn down with
  // their nodes by the next call's canvas.replaceChildren(). Without the
  // signal each revisit to the roadmap would add another copy on top of the
  // last, permanently.
  canvas.addEventListener('pointerdown', (event) => {
    const group = event.target.closest('.node');
    const point = canvas.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const local = point.matrixTransform(canvas.getScreenCTM().inverse());
    if (group) {
      const name = group.dataset.name;
      dragging = { name, offsetX: local.x - positions.get(name).x * scale - pan.x,
                   offsetY: local.y - positions.get(name).y * scale - pan.y, moved: false };
    } else {
      dragging = { name: null, offsetX: local.x - pan.x, offsetY: local.y - pan.y, moved: false };
      canvas.classList.add('dragging');
      canvas.setPointerCapture(event.pointerId);
    }
  }, { signal });

  canvas.addEventListener('pointermove', (event) => {
    if (!dragging) return;
    const point = canvas.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const local = point.matrixTransform(canvas.getScreenCTM().inverse());
    dragging.moved = true;
    if (dragging.name) {
      positions.set(dragging.name, {
        ...positions.get(dragging.name),
        x: (local.x - dragging.offsetX - pan.x) / scale,
        y: (local.y - dragging.offsetY - pan.y) / scale,
      });
      place(dragging.name);
      redrawEdges();
    } else {
      pan = { x: local.x - dragging.offsetX, y: local.y - dragging.offsetY };
      applyViewport();
    }
  }, { signal });

  canvas.addEventListener('pointerup', (event) => {
    canvas.classList.remove('dragging');
    if (dragging && dragging.name && dragging.moved) save(data.root, positions);
    suppressClick = Boolean(dragging && dragging.name && dragging.moved);
    dragging = null;
    canvas.releasePointerCapture(event.pointerId);
  }, { signal });

  // An interrupted gesture (e.g. the OS steals the pointer for a scroll)
  // must not leave the canvas permanently in "dragging" mode.
  canvas.addEventListener('pointercancel', () => {
    canvas.classList.remove('dragging');
    dragging = null;
  }, { signal });

  applyViewport();

  return {
    reset() {
      for (const [name, pos] of computed) positions.set(name, { ...pos });
      for (const name of positions.keys()) place(name);
      redrawEdges();
      try {
        window.localStorage.removeItem(storageKey(data.root));
      } catch {
        /* storage unavailable; the in-memory reset still applied */
      }
    },
    zoomBy(factor) {
      scale = Math.min(2.5, Math.max(0.35, scale * factor));
      applyViewport();
    },
  };
}
