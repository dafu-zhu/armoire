// A pane width is how one person likes looking at one folder in one browser,
// so it stays in localStorage. Status is the opposite and lives on the server.

const MIN = 180;
const MAX = 600;
const STEP = 16;

function key(root) {
  return `armoire:divider:${root}`;
}

export function initDivider(handle, pane, root) {
  function apply(width, persist) {
    const clamped = Math.min(MAX, Math.max(MIN, width));
    pane.style.flex = `0 0 ${clamped}px`;
    handle.setAttribute('aria-valuenow', String(Math.round(clamped)));
    if (persist) {
      try {
        window.localStorage.setItem(key(root), String(Math.round(clamped)));
      } catch {
        // Quota or a privacy mode that blocks storage. The drag still applied.
      }
    }
    return clamped;
  }

  handle.setAttribute('role', 'separator');
  handle.setAttribute('aria-orientation', 'vertical');
  handle.setAttribute('aria-valuemin', String(MIN));
  handle.setAttribute('aria-valuemax', String(MAX));
  handle.tabIndex = 0;

  let saved = NaN;
  try {
    saved = Number(window.localStorage.getItem(key(root)));
  } catch {
    // Storage unavailable; fall through to the default width.
  }
  apply(Number.isFinite(saved) && saved > 0 ? saved : pane.getBoundingClientRect().width, false);

  let dragging = false;
  handle.addEventListener('pointerdown', (event) => {
    dragging = true;
    handle.setPointerCapture(event.pointerId);
    event.preventDefault();
  });
  handle.addEventListener('pointermove', (event) => {
    if (!dragging) return;
    apply(event.clientX - pane.getBoundingClientRect().left, false);
  });
  handle.addEventListener('pointerup', (event) => {
    if (!dragging) return;
    dragging = false;
    handle.releasePointerCapture(event.pointerId);
    apply(pane.getBoundingClientRect().width, true);
  });
  // An interrupted gesture must not leave the handle stuck in drag mode.
  handle.addEventListener('pointercancel', () => { dragging = false; });

  handle.addEventListener('keydown', (event) => {
    const width = pane.getBoundingClientRect().width;
    if (event.key === 'ArrowRight') apply(width + STEP, true);
    else if (event.key === 'ArrowLeft') apply(width - STEP, true);
    else if (event.key === 'Home') apply(MIN, true);
    else if (event.key === 'End') apply(MAX, true);
    else return;
    event.preventDefault();
  });
}
