// The roadmap. dagre assigns ranks and positions; the SVG is rendered here so
// click targets, drag and styling stay under our control -- mermaid would emit
// a static picture we would then have to fight.

const NODE_W = 168;
const NODE_H = 62;
const CATEGORIES = 6;

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

function layout(projects) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 28, ranksep: 72, marginx: 24, marginy: 24 });
  g.setDefaultEdgeLabel(() => ({}));
  const known = new Set(projects.map((p) => p.name));
  for (const project of projects) {
    g.setNode(project.name, { width: NODE_W, height: NODE_H });
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

export function renderRoadmap(canvas, data, onOpen) {
  const projects = data.projects || [];
  const g = layout(projects);
  const order = new Map();
  const positions = new Map();

  canvas.replaceChildren();
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

  const blockedNames = new Set(
    projects.filter((p) => p.blocked_by.length > 0).map((p) => p.name),
  );

  // Issues are strings of the form "<project>: <what is wrong>". A node whose
  // name leads an issue gets a marker, so a missing folder or an unknown
  // blocker is visible on the graph and not only in a rail nobody opened.
  const flagged = new Set(
    (data.issues || [])
      .map((issue) => issue.split(':')[0].trim())
      .filter((name) => projects.some((p) => p.name === name)),
  );

  for (const project of projects) {
    const pos = positions.get(project.name);
    if (!pos) continue;
    const group = svgEl('g', {
      class: `node ${categoryClass(project.category, order)}${
        blockedNames.has(project.name) ? ' blocked' : ''
      }`,
      'data-name': project.name,
      transform: `translate(${pos.x - NODE_W / 2},${pos.y - NODE_H / 2})`,
      tabindex: '0',
      role: 'button',
    });
    group.append(svgEl('rect', { width: NODE_W, height: NODE_H }));

    const title = svgEl('text', { x: 12, y: 24 });
    title.textContent = project.name;
    group.append(title);

    const subtitle = project.due || project.note || '';
    if (subtitle) {
      const sub = svgEl('text', { x: 12, y: 42, class: 'node-sub' });
      sub.textContent = subtitle;
      group.append(sub);
    }

    const badge = svgEl('text', {
      x: NODE_W - 12, y: 24, class: 'node-badge', 'text-anchor': 'end',
    });
    badge.textContent = `${project.commits}`;
    group.append(badge);

    if (flagged.has(project.name)) {
      const warn = svgEl('text', {
        x: NODE_W - 12, y: NODE_H - 12, class: 'node-warn', 'text-anchor': 'end',
      });
      warn.textContent = '!';
      const reason = svgEl('title');
      reason.textContent = (data.issues || [])
        .filter((issue) => issue.startsWith(`${project.name}:`))
        .join('\n');
      warn.append(reason);
      group.append(warn);
    }

    group.addEventListener('click', () => onOpen(project.name));
    group.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') onOpen(project.name);
    });
    nodeLayer.append(group);
  }

  const graph = g.graph();
  canvas.setAttribute('viewBox', `0 0 ${graph.width || 800} ${graph.height || 400}`);

  return { positions, redrawEdges, viewport, nodeLayer };
}
