// Status is server state, not browser state: it is a claim about the work and
// must be the same in every browser. Positions are the opposite and stay in
// localStorage.

export const STATUS_ORDER = ['not-started', 'active', 'paused', 'done'];

const GLYPH = {
  'not-started': '○',
  active: '●',
  paused: '◐',
  done: '✓',
};

export function nextStatus(current) {
  const at = STATUS_ORDER.indexOf(current);
  return STATUS_ORDER[(at + 1) % STATUS_ORDER.length];
}

export function glyphFor(status) {
  return GLYPH[status] || GLYPH.active;
}

export async function setStatus(name, status) {
  const response = await fetch('/api/status', {
    method: 'PUT',
    // The server requires this header. A cross-origin page cannot set it
    // without a preflight armoire never answers, which is what stops any
    // other tab writing here.
    headers: { 'Content-Type': 'application/json', 'X-Armoire': '1' },
    body: JSON.stringify({ name, status }),
  });
  if (!response.ok) throw new Error(`status ${response.status}`);
}

// Per-project write serialization, plus a staleness guard for rollback.
// Keyed by project name at module scope -- shared by every caller, rather
// than one copy per renderer -- so two rapid clicks on the same project's
// status chip can never let their PUTs reach the server out of order, and a
// failed write only rolls back its caller's optimistic UI if it is still
// the most recent click for that project, regardless of which tree (the
// roadmap graph, the category column) issued which click. A project's chip
// only ever lives in one tree at a time -- renderRoadmap draws the
// non-isolated projects, renderCategories the isolated ones, and a project
// cannot be both -- so nothing here has to reconcile two chips for the same
// project disagreeing; sharing the queue is what stops a second module from
// having to reinvent the same ordering guarantee roadmap.js already earned.
const writeQueue = new Map();
const writeToken = new Map();

export function writeStatus(name, status, onStaleFailure) {
  const previous = writeQueue.get(name) || Promise.resolve();
  const token = (writeToken.get(name) || 0) + 1;
  writeToken.set(name, token);
  // Chained onto the *settlement* (success or failure, via the two-argument
  // .then) of this project's previous write, so only one PUT for a given
  // project is ever in flight -- there is nothing left for the server to
  // reorder.
  const write = previous
    .then(
      () => setStatus(name, status),
      () => setStatus(name, status),
    )
    .catch(() => {
      // Only the *latest* click for this project may roll back: an
      // intervening click has already moved the optimistic state (and
      // queued its own write) past this one, and rolling back to this
      // click's view of "previous" would show a status the server never
      // actually held for either click.
      if (writeToken.get(name) === token) onStaleFailure();
    });
  writeQueue.set(name, write);
  return write;
}
