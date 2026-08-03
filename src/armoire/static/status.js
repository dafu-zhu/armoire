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

const LABEL = {
  'not-started': 'Not started',
  active: 'Active',
  paused: 'Paused',
  done: 'Done',
};

export function nextStatus(current) {
  const at = STATUS_ORDER.indexOf(current);
  return STATUS_ORDER[(at + 1) % STATUS_ORDER.length];
}

// The one place an unrecognised status (an omitted field in a
// stubbed/malformed payload; the server itself always sends a valid one)
// gets a fallback, so every reader -- roadmap.js's border/glyph/aria-label/
// isBlocked, categories.js's item class/glyph/aria-label/cycle -- agrees on
// the same value instead of each inventing its own. 'not-started' matches
// the server's own DEFAULT_STATUS (projects.py) and, for free, matches what
// nextStatus(undefined) already returns on its own (indexOf -1, +1 wraps to
// 0 = STATUS_ORDER[0]) -- a caller that skipped normalising and called
// nextStatus() directly on a raw payload value used to disagree with a
// caller that normalised first about what a click from the same bad input
// produces; now both land on the same value.
export function normalizeStatus(status) {
  return STATUS_ORDER.includes(status) ? status : 'not-started';
}

export function glyphFor(status) {
  return GLYPH[status] || GLYPH['not-started'];
}

export function labelFor(status) {
  return LABEL[status] || LABEL['not-started'];
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

// `onLatestFailure` fires when this write's failure is *not* stale -- i.e.
// this is still the most recent click for `name`. (Named for the condition
// that triggers it, not for staleness itself, which is the case it must
// stay silent for.) Optional: a caller that never fails its writes, or
// doesn't care to roll back, may omit it.
export function writeStatus(name, status, onLatestFailure) {
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
      if (writeToken.get(name) === token) onLatestFailure?.();
    });
  writeQueue.set(name, write);
  return write;
}
