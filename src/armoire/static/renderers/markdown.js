// Markdown with math and diagrams, and relative links rewired to in-app routes.

import { encodeHashPath } from '../format.js';

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

// One request's worth of paths. The handler takes a batch of any size, and
// uvicorn was measured accepting a 34KB request line without complaint, so
// this is not working around a limit anyone here has actually hit -- it caps
// a query string that would otherwise grow with the document, on the general
// principle that a URL nobody bounds is a URL that eventually meets someone
// else's bound. A link-heavy index page costs a second request; nothing else
// costs a first one.
const EXISTS_BATCH = 50;

// A relative link is only as good as the file it names, and the file may have
// been renamed, archived, or never have existed. Following one used to
// replace the document with a "no such file" card under a changed URL, which
// costs the reader their place to tell them what the link itself could have
// said. So the targets are checked once, on render, and a dead one is struck
// through and stripped of its href.
//
// Stripped, not merely intercepted: an <a> with no href is not a link to
// anything, which is exactly the claim being made, and it takes middle click,
// ctrl-click and Enter-on-focus out with the same stroke -- each of those
// bypasses a click handler and would otherwise still open the dead path.
//
// Any failure here leaves every link exactly as it was. An unreachable
// server is not evidence that a link is dead, and a document full of
// wrongly-struck-through links would be a worse outcome than the error card
// this replaces.
async function markDeadLinks(links) {
  const missing = new Set();
  try {
    // Deduplicated: a document that links the same file from ten places asks
    // about it once.
    const paths = [...new Set(links.map((link) => link.path))];
    for (let start = 0; start < paths.length; start += EXISTS_BATCH) {
      const query = paths
        .slice(start, start + EXISTS_BATCH)
        .map((path) => `path=${encodeURIComponent(path)}`)
        .join('&');
      const response = await fetch(`/api/exists?${query}`);
      if (!response.ok) return;
      for (const path of (await response.json()).missing) missing.add(path);
    }
  } catch {
    return;
  }
  for (const { anchor, path } of links) {
    if (!missing.has(path)) continue;
    anchor.removeAttribute('href');
    // add, not assignment: a class the author wrote survived the sanitizer
    // and is not this function's to discard.
    anchor.classList.add('broken');
    anchor.title = `missing: ${path}`;
  }
}

function rewriteLinks(root, basePath) {
  const relative = [];
  for (const anchor of root.querySelectorAll('a[href]')) {
    const href = anchor.getAttribute('href');
    // Absolute URLs, anchors and mailto: are left exactly as the author wrote them.
    if (/^([a-z]+:|#|\/\/)/i.test(href)) continue;
    const path = normalise(`${basePath}/${href}`);
    anchor.setAttribute('href', `#/browse/${encodeHashPath(path)}`);
    // Collected rather than checked here: these are the only links that
    // resolve to a path inside the served folder, and so the only ones whose
    // target armoire can be asked about at all.
    relative.push({ anchor, path });
  }
  for (const img of root.querySelectorAll('img[src]')) {
    const src = img.getAttribute('src');
    if (/^([a-z]+:|\/\/|data:)/i.test(src)) continue;
    img.setAttribute('src', `/api/raw?path=${encodeURIComponent(normalise(`${basePath}/${src}`))}`);
  }
  return relative;
}

export function renderMarkdown(container, data, path) {
  const base = dirnameOf(path);
  const body = document.createElement('div');
  body.className = 'markdown-body';

  // Mermaid blocks are pulled out before marked runs so it does not escape them.
  // \r?\n, not \n: a CRLF document puts \r between the fence and the newline,
  // and an \n-anchored pattern silently misses it -- the fence then falls
  // through to highlight.js as an unknown language instead of rendering.
  const diagrams = [];
  const source = data.text.replace(/```mermaid\r?\n([\s\S]*?)```/g, (_, code) => {
    diagrams.push(code);
    return `<div class="mermaid-slot" data-index="${diagrams.length - 1}"></div>`;
  });

  // marked does not sanitize, and this renders files the user may not have
  // written. Sanitize before injection: KaTeX and Mermaid run afterwards and
  // insert their own markup into the already-cleaned DOM.
  body.innerHTML = DOMPurify.sanitize(marked.parse(source));
  const links = rewriteLinks(body, base);

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

  // Unawaited, like the mermaid render below: this function's contract is to
  // return the status-bar label synchronously, and the document is readable
  // the moment it is appended. The marking arrives a round trip later and
  // touches nothing but the anchors it strikes out -- if the reader has
  // navigated away by then it lands on a detached body, harmlessly.
  if (links.length) markDeadLinks(links);

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
