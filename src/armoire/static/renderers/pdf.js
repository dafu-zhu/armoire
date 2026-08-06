function rawUrl(path) {
  return `/api/raw?path=${encodeURIComponent(path)}`;
}

function fileName(path) {
  const parts = String(path).split('/').filter(Boolean);
  return parts.at(-1) || path || 'PDF';
}

export function renderPdf(container, data, path) {
  container.classList.add('pdf-content');
  container.closest('#main')?.classList.add('pdf-main');

  const shell = document.createElement('section');
  shell.className = 'pdf-shell';
  shell.setAttribute('aria-label', 'PDF reader');

  const toolbar = document.createElement('div');
  toolbar.className = 'pdf-reader-toolbar';

  const title = document.createElement('div');
  title.className = 'pdf-reader-title';
  title.textContent = fileName(path);

  toolbar.append(title);

  const frame = document.createElement('iframe');
  frame.className = 'pdf';
  frame.title = fileName(path);
  frame.src = `${rawUrl(path)}#toolbar=0&navpanes=0&view=FitH`;

  shell.append(toolbar, frame);
  container.append(shell);
  return 'pdf';
}
