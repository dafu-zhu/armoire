export function renderNotebook(container, data) {
  const body = document.createElement('div');
  body.className = 'notebook-body';
  body.innerHTML = data.html;
  body.querySelectorAll('pre code').forEach((block) => hljs.highlightElement(block));
  container.append(body);
  return 'notebook';
}
