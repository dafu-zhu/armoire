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
