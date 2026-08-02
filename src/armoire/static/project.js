// One project: who blocks it, what it blocks, what is inside it, and what
// actually moved there recently.

function heading(level, text) {
  const el = document.createElement(level);
  el.textContent = text;
  return el;
}

function nameList(label, names) {
  const wrap = document.createElement('p');
  wrap.append(document.createTextNode(`${label}: `));
  wrap.append(document.createTextNode(names.length ? names.join(', ') : 'nothing'));
  return wrap;
}

function ago(seconds) {
  const days = (Date.now() / 1000 - seconds) / 86400;
  if (days < 1) return 'today';
  if (days < 2) return 'yesterday';
  if (days < 30) return `${Math.floor(days)} days ago`;
  return `${Math.floor(days / 30)} months ago`;
}

export async function renderProject(container, name, onOpenFile) {
  const response = await fetch(`/api/project/${encodeURIComponent(name)}`);
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  const data = await response.json();

  container.replaceChildren();
  const root = document.createElement('div');
  root.className = 'project-detail';

  root.append(heading('h1', data.project.name));
  if (data.project.note) root.append(heading('p', data.project.note));
  if (data.project.due) root.append(heading('p', `Due ${data.project.due}`));

  root.append(nameList('Blocked by', data.project.blocked_by));
  root.append(nameList('Blocks', data.blocks));

  root.append(heading('h2', 'Files'));
  const files = document.createElement('ul');
  for (const file of data.files) {
    const li = document.createElement('li');
    const link = document.createElement('a');
    link.href = '#';
    link.textContent = file.is_dir ? `${file.name}/` : file.name;
    link.addEventListener('click', (event) => {
      event.preventDefault();
      onOpenFile(file.path);
    });
    li.append(link);
    files.append(li);
  }
  root.append(files);

  if (data.commits.length) {
    root.append(heading('h2', 'Recent commits'));
    const commits = document.createElement('ul');
    for (const commit of data.commits) {
      const li = document.createElement('li');
      li.textContent = `${commit.sha}  ${commit.subject} — ${ago(commit.when)}`;
      commits.append(li);
    }
    root.append(commits);
  }

  container.append(root);
  return `project · ${data.files.length} entries`;
}
