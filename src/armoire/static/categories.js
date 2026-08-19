// Projects that participate in no dependency have no place in the graph.
// Phase 2 let dagre park them mid-canvas, where they pushed the real roots
// off-centre and read as part of a structure they are not in.

import { glyphFor, nextStatus, normalizeStatus, writeStatus } from './status.js';
import { categoryClass } from './palette.js';

function applyHabitState(item, project) {
  item.classList.toggle('habit-ready', project.habit_unlocked);
  item.classList.toggle('habit-locked', !project.habit_unlocked);
  item.querySelector('.entry-state').textContent = project.habit_unlocked
    ? 'Ready'
    : `Locked · ${(project.habit_locked_by || []).join(', ')}`;
}

export function refreshHabitStates(container, data) {
  const projects = data.projects || [];
  const statuses = new Map(projects.map((project) => [project.name, normalizeStatus(project.status)]));
  const items = [...container.querySelectorAll('.habit-entry')];
  for (const project of projects.filter((candidate) => candidate.is_habit)) {
    project.habit_locked_by = project.blocked_by.filter(
      (blocker) => statuses.get(blocker) !== 'done',
    );
    project.habit_unlocked = project.habit_locked_by.length === 0;
    const item = items.find((candidate) => candidate.dataset.name === project.name);
    if (item) applyHabitState(item, project);
  }
}

// Returns how many containers were drawn, so app.js can hide the column when
// there are none. An empty bordered box costs 240px of canvas and says
// nothing; "the category column is permanent, not another toggle" (the spec)
// is about the affordance never being something the user has to switch on,
// not about rendering a container with nothing in it.
//
// `order` is the shared category->colour map (palette.js), built by app.js
// over the whole payload. This function only ever sees the isolated half, so
// a map built here would disagree with the graph's.
//
// `callbacks` shares roadmap.js's selection/navigation actions plus
// `onStatusChange`, which keeps Habit gates current while a prerequisite chip
// changes without reloading the payload.
export function renderCategories(container, data, callbacks, order) {
  const { onSelect, onOpenFolder, onStatusChange } = callbacks;
  container.replaceChildren();
  const isolated = (data.projects || []).filter((p) => p.isolated || p.is_habit);
  if (!isolated.length) return 0;
  const issues = data.issues || [];

  const groups = new Map();
  for (const project of isolated) {
    const key = project.category || 'Uncategorised';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(project);
  }

  for (const [name, members] of groups) {
    const section = document.createElement('section');
    section.className = 'category';
    const heading = document.createElement('h3');
    heading.textContent = name;
    section.append(heading);

    // Every member of a group shares one category by construction -- the group
    // key is that category -- so any member answers for the whole group.
    // members[0].category, not `name`: an uncategorised group is keyed on the
    // display string "Uncategorised", which is not a category and must reach
    // categoryClass as the absent value it stands for, or a real category
    // literally called "Uncategorised" and the fallback would collide. Read
    // once per group and carried into every className assignment below --
    // status cycling below rewrites className wholesale, and a version that
    // dropped this would silently strip the entry back to an uncoloured box
    // on the very first click.
    const catClass = categoryClass(members[0].category, order);

    const list = document.createElement('ul');
    for (const project of members) {
      const isHabit = project.is_habit === true;
      // Seeded the same way, at the same seam, as roadmap.js's own
      // `statuses` Map -- an unrecognised status must not reach glyphFor,
      // nextStatus or the `status-…` class raw, or this column and the graph
      // can disagree about what a click on the same bad input produces.
      const initialStatus = normalizeStatus(project.status);

      // The whole box is the click target -- an <li role="button">, styled
      // in app.css to look like a graph node (same category colour, same
      // border-weight/style-per-status language) -- mirroring roadmap.js's
      // own <g role="button"> node group, not a single line of link text
      // inside an otherwise inert row.
      const item = document.createElement('li');
      item.className = isHabit
        ? `entry ${catClass} habit-entry ${project.habit_unlocked ? 'habit-ready' : 'habit-locked'}`
        : `entry ${catClass} status-${initialStatus}`;
      item.setAttribute('data-name', project.name);
      item.tabIndex = 0;
      item.setAttribute('role', 'button');

      const head = document.createElement('div');
      head.className = 'entry-head';

      const label = document.createElement('span');
      label.className = 'entry-name';
      label.textContent = project.name;
      head.append(label);

      // The same registry-issue affordance a graph node gets from its own
      // `.node-warn` (roadmap.js): an isolated project has no node to carry
      // it, so without this, an issue against it -- like Backlog's unknown
      // blocked_by in sample_root -- exists only as a number in the status
      // strip, readable nowhere. `title` is the HTML equivalent of the SVG
      // node's nested <title> tooltip. Placed beside the chip, same as the
      // node's own marker (roadmap.js).
      const projectIssues = issues.filter((issue) => issue.startsWith(`${project.name}:`));
      if (projectIssues.length) {
        const warn = document.createElement('span');
        warn.className = 'entry-warn';
        warn.textContent = '!';
        warn.setAttribute('title', projectIssues.join('\n'));
        head.append(warn);
      }

      if (isHabit) {
        const state = document.createElement('p');
        state.className = 'entry-state';
        item.append(head, state);
        applyHabitState(item, project);
      } else {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'status-chip';
        chip.textContent = glyphFor(initialStatus);
        chip.setAttribute('aria-label', `Status: ${initialStatus}. Click to change.`);
        let status = initialStatus;
        chip.addEventListener('click', (event) => {
          // The chip lives inside the item; stopping propagation here keeps
          // the chip's own click from also being read as a click on the box,
          // the same isolation roadmap.js's node chip keeps from its node
          // group.
          event.stopPropagation();
          const previous = status;
          status = nextStatus(status);
          onStatusChange?.(project.name, status);
          chip.textContent = glyphFor(status);
          chip.setAttribute('aria-label', `Status: ${status}. Click to change.`);
          item.className = `entry ${catClass} status-${status}`;
          // writeStatus (status.js) serializes this project's writes -- across
          // both this module and roadmap.js -- and only calls back here if
          // this write failed and is still the latest click for this project.
          // A given project's chip lives in exactly one of the two trees (this
          // one draws only isolated projects, roadmap.js only the rest), so
          // there is never a second chip for the same project to reconcile
          // against; sharing the queue is what still stops two rapid clicks on
          // this one chip from racing their own PUTs out of order.
          writeStatus(project.name, status, () => {
            status = previous;
            onStatusChange?.(project.name, status);
            chip.textContent = glyphFor(status);
            chip.setAttribute('aria-label', `Status: ${status}. Click to change.`);
            item.className = `entry ${catClass} status-${status}`;
          });
        });
        head.append(chip);
        item.append(head);
      }

      if (project.due) {
        const due = document.createElement('p');
        due.className = 'entry-due';
        due.textContent = `Due ${project.due}`;
        item.append(due);
      }
      if (project.note) {
        const note = document.createElement('p');
        note.className = 'entry-note';
        note.textContent = project.note;
        item.append(note);
      }

      // Same click/dblclick split as roadmap.js's node group: a single
      // click opens the side panel immediately, a double click (which fires
      // click, click, dblclick on the same target) additionally navigates
      // straight into the folder. Firing the click's own effect right away
      // rather than deferring it behind a timer -- unlike the breadcrumb
      // root crumb in app.js, which must defer because navigating on click
      // would re-render the crumb (and destroy its own listeners) before
      // dblclick could ever reach it -- matters here because a deferred
      // timer races the browser's own, OS-configured double-click window:
      // if that window is longer than the timer's delay, the single click's
      // action still fires on schedule and then dblclick fires again on top
      // of it, which is exactly what made two ordinary, unhurried clicks
      // look like the panel "opened, then vanished".
      item.addEventListener('click', () => onSelect(project));
      item.addEventListener('dblclick', () => onOpenFolder(project));
      item.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') onSelect(project);
      });

      list.append(item);
    }
    section.append(list);
    container.append(section);
  }
  return groups.size;
}
