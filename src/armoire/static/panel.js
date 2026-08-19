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

export function openPanel(container, project, onOpenFolder, options = {}) {
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

  if (status === 'conditional-done') {
    const section = document.createElement('section');
    section.className = 'panel-conditional-notes';
    const heading = document.createElement('div');
    heading.className = 'panel-note-heading';
    const label = document.createElement('strong');
    label.textContent = 'Notes';
    heading.append(label);

    if (options.editConditionalNote) {
      const textarea = document.createElement('textarea');
      textarea.id = 'conditional-note-input';
      textarea.value = project.conditional_note || '';
      textarea.setAttribute('aria-label', 'Notes');
      textarea.rows = 5;

      const error = document.createElement('p');
      error.className = 'panel-note-error';
      error.setAttribute('role', 'alert');
      error.hidden = true;

      const actions = document.createElement('div');
      actions.className = 'panel-note-actions';
      const cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.textContent = 'Cancel';
      cancel.addEventListener('click', () => {
        if (options.onCancelConditionalNote) options.onCancelConditionalNote();
        else openPanel(container, project, onOpenFolder, { ...options, editConditionalNote: false });
      });
      const save = document.createElement('button');
      save.type = 'button';
      save.className = 'primary';
      save.textContent = 'Save changes';
      save.addEventListener('click', async () => {
        const note = textarea.value.trim();
        if (!note) {
          error.textContent = 'Notes are required for conditional done.';
          error.hidden = false;
          textarea.focus();
          return;
        }
        save.disabled = true;
        cancel.disabled = true;
        error.hidden = true;
        const saved = await options.onSaveConditionalNote?.(note);
        if (!saved) {
          error.textContent = 'Notes could not be saved. Try again.';
          error.hidden = false;
          save.disabled = false;
          cancel.disabled = false;
        }
      });
      actions.append(cancel);
      if (options.onMarkFullyDone) {
        const markDone = document.createElement('button');
        markDone.type = 'button';
        markDone.textContent = 'Mark fully done';
        markDone.addEventListener('click', async () => {
          markDone.disabled = true;
          save.disabled = true;
          cancel.disabled = true;
          error.hidden = true;
          const saved = await options.onMarkFullyDone();
          if (!saved) {
            error.textContent = 'Status could not be saved. Try again.';
            error.hidden = false;
            markDone.disabled = false;
            save.disabled = false;
            cancel.disabled = false;
          }
        });
        actions.append(markDone);
      }
      actions.append(save);
      section.append(heading, textarea, error, actions);
    } else {
      const edit = document.createElement('button');
      edit.type = 'button';
      edit.className = 'panel-note-edit';
      edit.setAttribute('aria-label', 'Edit notes');
      edit.textContent = '✎';
      edit.addEventListener('click', () => {
        openPanel(container, project, onOpenFolder, { ...options, editConditionalNote: true });
      });
      heading.append(edit);
      const note = document.createElement('p');
      note.className = 'panel-conditional-note';
      note.textContent = project.conditional_note;
      section.append(heading, note);
    }
    container.append(section);
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
