// Projects that participate in no dependency have no place in the graph.
// Phase 2 let dagre park them mid-canvas, where they pushed the real roots
// off-centre and read as part of a structure they are not in.

import { glyphFor, nextStatus, writeStatus } from './status.js';

export function renderCategories(container, data, onOpen) {
  container.replaceChildren();
  const isolated = (data.projects || []).filter((p) => p.isolated);
  if (!isolated.length) return;

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

    const list = document.createElement('ul');
    for (const project of members) {
      const item = document.createElement('li');
      item.className = `entry status-${project.status}`;
      item.setAttribute('data-name', project.name);

      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'status-chip';
      chip.textContent = glyphFor(project.status);
      chip.setAttribute('aria-label', `Status: ${project.status}. Click to change.`);
      let status = project.status;
      chip.addEventListener('click', (event) => {
        // The chip lives inside the item; nothing else in this list listens
        // for a click today, but stopping it here keeps the chip's own
        // click from ever being read as a click on the row, the same
        // isolation roadmap.js's node chip keeps from its node group.
        event.stopPropagation();
        const previous = status;
        status = nextStatus(status);
        chip.textContent = glyphFor(status);
        item.className = `entry status-${status}`;
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
          chip.textContent = glyphFor(status);
          item.className = `entry status-${status}`;
        });
      });

      const label = document.createElement('button');
      label.type = 'button';
      label.className = 'entry-name';
      label.textContent = project.name;
      label.addEventListener('click', () => onOpen(project.name));

      item.append(chip, label);
      if (project.note) {
        const note = document.createElement('p');
        note.className = 'entry-note';
        note.textContent = project.note;
        item.append(note);
      }
      list.append(item);
    }
    section.append(list);
    container.append(section);
  }
}
