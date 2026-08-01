// Markdown with math and diagrams, and relative links rewired to in-app routes.

let mermaidReady = false;

function dirnameOf(path) {
  const cut = path.lastIndexOf('/');
  return cut === -1 ? '' : path.slice(0, cut);
}

function normalise(path) {
  const out = [];
  for (const part of path.split('/')) {
    if (!part || part === '.') continue;
    if (part === '..') out.pop();
    else out.push(part);
  }
  return out.join('/');
}

function rewriteLinks(root, basePath) {
  for (const anchor of root.querySelectorAll('a[href]')) {
    const href = anchor.getAttribute('href');
    // Absolute URLs, anchors and mailto: are left exactly as the author wrote them.
    if (/^([a-z]+:|#|\/\/)/i.test(href)) continue;
    anchor.setAttribute('href', `#/${normalise(`${basePath}/${href}`)}`);
  }
  for (const img of root.querySelectorAll('img[src]')) {
    const src = img.getAttribute('src');
    if (/^([a-z]+:|\/\/|data:)/i.test(src)) continue;
    img.setAttribute('src', `/api/raw?path=${encodeURIComponent(normalise(`${basePath}/${src}`))}`);
  }
}

export function renderMarkdown(container, data, path) {
  const base = dirnameOf(path);
  const body = document.createElement('div');
  body.className = 'markdown-body';

  // Mermaid blocks are pulled out before marked runs so it does not escape them.
  const diagrams = [];
  const source = data.text.replace(/```mermaid\n([\s\S]*?)```/g, (_, code) => {
    diagrams.push(code);
    return `<div class="mermaid-slot" data-index="${diagrams.length - 1}"></div>`;
  });

  body.innerHTML = marked.parse(source);
  rewriteLinks(body, base);

  body.querySelectorAll('pre code').forEach((block) => hljs.highlightElement(block));

  renderMathInElement(body, {
    delimiters: [
      { left: '$$', right: '$$', display: true },
      { left: '$', right: '$', display: false },
      { left: '\\[', right: '\\]', display: true },
      { left: '\\(', right: '\\)', display: false },
    ],
    throwOnError: false,
  });

  container.append(body);

  if (diagrams.length) {
    if (!mermaidReady) {
      mermaid.initialize({ startOnLoad: false, theme: 'neutral' });
      mermaidReady = true;
    }
    body.querySelectorAll('.mermaid-slot').forEach(async (slot, i) => {
      try {
        const { svg } = await mermaid.render(`mermaid-${Date.now()}-${i}`, diagrams[slot.dataset.index]);
        slot.innerHTML = svg;
      } catch (error) {
        slot.className = 'error';
        slot.textContent = `Diagram failed: ${error.message}`;
      }
    });
  }

  return 'markdown';
}
