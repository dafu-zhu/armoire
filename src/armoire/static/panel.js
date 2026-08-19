// The roadmap's quick-look drawer: a single click's worth of detail --
// status, due date, note -- without leaving the graph. Blocked-by/blocks are
// already visible as edges on the graph itself, so this does not repeat them
// in text, and it carries no file list or commit history: that is what
// double-clicking (or this panel's own "Open project files" button) is for.

import { glyphFor, labelFor, normalizeStatus } from './status.js';

function field(label, value) {
  const p = document.createElement('p');
  p.className = 'panel-field';
  const tag = document.createElement('span');
  tag.className = 'label';
  tag.textContent = `${label}:`;
  p.append(tag, document.createTextNode(value));
  return p;
}

// Module-scoped, not per-call: only one panel instance exists (#project-panel
// in index.html), so a later open() must remove the previous open()'s own
// listener rather than stacking a second one that outlives it.
let escapeHandler = null;

export function closePanel(container) {
  container.hidden = true;
  container.replaceChildren();
  if (escapeHandler) {
    document.removeEventListener('keydown', escapeHandler);
    escapeHandler = null;
  }
}

export function openPanel(container, project, onOpenFolder) {
  container.replaceChildren();
  const isHabit = project.is_habit === true;
  const status = normalizeStatus(project.status);

  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'panel-close';
  close.setAttribute('aria-label', 'Close');
  close.textContent = '×';
  close.addEventListener('click', () => closePanel(container));

  const title = document.createElement('h2');
  title.textContent = project.name;

  const statusLine = document.createElement('p');
  if (isHabit) {
    statusLine.className = `panel-field panel-habit-state ${
      project.habit_unlocked ? 'habit-ready' : 'habit-locked'
    }`;
    statusLine.textContent = project.habit_unlocked
      ? 'Ready'
      : `Locked · ${(project.habit_locked_by || []).join(', ')}`;
  } else {
    statusLine.className = 'panel-field';
    const glyph = document.createElement('span');
    glyph.className = `panel-status-glyph status-${status}`;
    glyph.textContent = glyphFor(status);
    statusLine.append(glyph, document.createTextNode(labelFor(status)));
  }

  container.append(close, title, statusLine);
  if (project.due) container.append(field('Due', project.due));
  if (project.category) container.append(field('Category', project.category));
  if (project.note) {
    const note = document.createElement('p');
    note.className = 'panel-note';
    note.textContent = project.note;
    container.append(note);
  }

  const open = document.createElement('button');
  open.type = 'button';
  open.className = 'panel-open';
  open.textContent = isHabit ? 'Open habit files' : 'Open project files';
  open.addEventListener('click', () => onOpenFolder(project));
  container.append(open);

  container.hidden = false;

  if (escapeHandler) document.removeEventListener('keydown', escapeHandler);
  escapeHandler = (event) => {
    if (event.key === 'Escape') closePanel(container);
  };
  document.addEventListener('keydown', escapeHandler);
}
