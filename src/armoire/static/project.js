// One project: who blocks it, what it blocks, what is inside it, and what
// actually moved there recently.

function heading(level, text) {
  const el = document.createElement(level);
  el.textContent = text;
  return el;
}

function relation(label, names) {
  const span = document.createElement('span');
  span.textContent = `${label}: ${names.length ? names.join(', ') : 'nothing'}`;
  return span;
}

function subtitleText(project) {
  const parts = [];
  if (project.note) parts.push(project.note);
  if (project.due) parts.push(`Due ${project.due}`);
  return parts.join(' — ');
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
  const subtitle = subtitleText(data.project);
  if (subtitle) {
    const p = document.createElement('p');
    p.className = 'subtitle';
    p.textContent = subtitle;
    root.append(p);
  }

  const relations = document.createElement('div');
  relations.className = 'relations';
  relations.append(relation('Blocked by', data.project.blocked_by));
  relations.append(relation('Blocks', data.blocks));
  root.append(relations);

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
      li.className = 'commit';
      const sha = document.createElement('span');
      sha.className = 'sha';
      sha.textContent = commit.sha;
      const subject = document.createElement('span');
      subject.className = 'subject';
      subject.textContent = commit.subject;
      const when = document.createElement('span');
      when.className = 'when';
      when.textContent = ago(commit.when);
      li.append(sha, subject, when);
      commits.append(li);
    }
    root.append(commits);
  }

  container.append(root);
  return `project · ${data.files.length} entries`;
}
