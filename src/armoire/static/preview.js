import { formatAge, formatSize } from './format.js';
import { renderListing } from './renderers/listing.js';
import { renderMarkdown } from './renderers/markdown.js';
import { renderCode } from './renderers/code.js';
import { renderPdf } from './renderers/pdf.js';
import { renderTable } from './renderers/table.js';
import { renderNotebook } from './renderers/notebook.js';

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    const error = new Error(body.detail || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function renderBinary(container, data, path) {
  const box = document.createElement('div');
  box.className = 'card';
  const body = document.createElement('div');
  body.className = 'empty';
  body.textContent = `No preview for ${path.split('.').pop()} files.`;
  const link = document.createElement('a');
  link.href = `/api/raw?path=${encodeURIComponent(path)}`;
  link.download = '';
  link.textContent = 'Download';
  body.append(document.createElement('br'), link);
  box.append(body);
  container.append(box);
  return 'no preview';
}

function renderImage(container, data, path) {
  const img = document.createElement('img');
  img.src = `/api/raw?path=${encodeURIComponent(path)}`;
  img.style.maxWidth = '100%';
  container.append(img);
  return 'image';
}

async function renderDirectory(container, path) {
  const data = await getJson(`/api/tree?path=${encodeURIComponent(path)}`);
  const status = renderListing(container, data, path);

  // GitHub's behaviour: a folder's README renders below its listing.
  const readme = data.files.find((f) => f.name.toLowerCase() === 'readme.md');
  if (readme) {
    const readmePath = path ? `${path}/${readme.name}` : readme.name;
    const card = document.createElement('div');
    card.className = 'card';
    const head = document.createElement('div');
    head.className = 'card-head';
    head.textContent = readme.name;
    const body = document.createElement('div');
    body.className = 'card-body';
    card.append(head, body);
    container.append(card);
    renderMarkdown(body, await getJson(`/api/preview?path=${encodeURIComponent(readmePath)}`), readmePath);
  }
  return status;
}

export async function renderPreview(container, path, page = 0) {
  container.replaceChildren();

  // The root and any directory come back from /api/tree, not /api/preview.
  if (path === '') return renderDirectory(container, path);

  let data;
  try {
    data = await getJson(`/api/preview?path=${encodeURIComponent(path)}&page=${page}`);
  } catch (error) {
    // /api/preview refuses directories with a 404; /api/tree serves them.
    if (error.status === 404) return renderDirectory(container, path);
    throw error;
  }

  const reload = (nextPage) => renderPreview(container, path, nextPage);

  let label;
  switch (data.kind) {
    case 'markdown':
      label = renderMarkdown(container, data, path);
      break;
    case 'code':
      label = renderCode(container, data, path);
      break;
    case 'notebook':
      label = renderNotebook(container, data, path);
      break;
    case 'table':
      label = renderTable(container, data, path, reload);
      break;
    case 'pdf':
      label = renderPdf(container, data, path);
      break;
    case 'image':
      label = renderImage(container, data, path);
      break;
    case 'error': {
      const box = document.createElement('div');
      box.className = 'error';
      box.textContent = data.message;
      container.append(box);
      label = 'error';
      break;
    }
    default:
      label = renderBinary(container, data, path);
  }

  // The spec's status strip: size, mtime and type, for every kind.
  return `${label} · ${formatSize(data.size)} · modified ${formatAge(data.mtime)}`;
}
