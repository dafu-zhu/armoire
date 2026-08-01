export function renderCode(container, data) {
  const pre = document.createElement('pre');
  pre.className = 'code card';
  const code = document.createElement('code');
  code.className = `language-${data.language}`;
  code.textContent = data.text;
  pre.append(code);
  hljs.highlightElement(code);
  container.append(pre);
  const lines = data.text.split('\n').length;
  return `${data.language} · ${lines} lines`;
}
