// The one way to reach registry.toml from the browser.
//
// The file lives in the per-user store, in a directory named with eight hex
// characters of a SHA-256 -- unique by construction and unmemorable by
// consequence. A `file://` link cannot help: browsers block navigation from
// an http: origin to file:, silently. So the server, which is a local process
// with the user's own permissions, does the opening.

// Replaces the button with the path when the launch fails -- no handler
// registered for .toml, no xdg-open on the box. Showing the path is the whole
// of the weakest option considered during design, kept as the fallback rather
// than the feature: the worst case still beats hunting for the hash by hand.
// Replaces rather than appends, because a button that just failed should not
// go on looking clickable.
function showPath(button, registryPath, reason) {
  const wrap = document.createElement('span');
  wrap.className = 'registry-fallback';

  const why = document.createElement('span');
  why.textContent = `Could not open it (${reason}) —`;

  const path = document.createElement('code');
  path.textContent = registryPath;

  const copy = document.createElement('button');
  copy.type = 'button';
  copy.className = 'registry-copy';
  copy.textContent = 'Copy';
  copy.addEventListener('click', async () => {
    // navigator.clipboard needs a secure context, and every browser counts
    // http://127.0.0.1 as one. No HTTPS, and no execCommand fallback, needed.
    try {
      await navigator.clipboard.writeText(registryPath);
      copy.textContent = 'Copied';
    } catch {
      // Clipboard permission denied. The path is already on screen and
      // selectable, so there is nothing further to offer.
      copy.textContent = 'Select it above';
      copy.disabled = true;
    }
  });

  wrap.append(why, path, copy);
  button.replaceWith(wrap);
}

// `registryPath` is null when armoire has no usable store for this folder
// (store.writes_inside), in which case there is no registry to open and no
// button to show.
export function mountRegistryButton(container, registryPath) {
  if (!registryPath) return null;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'registry-open';
  button.textContent = 'Edit registry';
  button.title = registryPath;
  button.addEventListener('click', async () => {
    // Disabled for the round trip: os.startfile returns immediately, but a
    // cold editor launch still takes a moment, and a second click would
    // launch a second copy.
    button.disabled = true;
    try {
      const response = await fetch('/api/registry/open', {
        method: 'POST',
        headers: { 'X-Armoire': '1' },
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || response.statusText);
      }
      button.disabled = false;
    } catch (error) {
      showPath(button, registryPath, String(error.message || error));
    }
  });
  container.append(button);
  return button;
}
