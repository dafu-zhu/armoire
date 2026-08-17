// Opens the current browse target outside the browser, through armoire's
// local server. Browsers cannot launch file:// paths from an http: page, so
// the process that already owns the served root performs the OS handoff.

function targetLabel(path) {
  return path || 'served folder';
}

export function initNativeOpen(button, status) {
  let currentPath = '';

  button.addEventListener('click', async () => {
    const path = currentPath;
    const label = targetLabel(path);
    button.disabled = true;
    try {
      const response = await fetch('/api/open', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Armoire': '1',
        },
        body: JSON.stringify({ path }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || response.statusText);
      }
      status.textContent = `Opened ${label}`;
    } catch (error) {
      status.textContent = `Could not open ${label}: ${String(error.message || error)}`;
    } finally {
      button.disabled = false;
    }
  });

  return {
    setPath(path) {
      currentPath = path;
      button.title = `Open ${targetLabel(path)} with the system default`;
    },
  };
}
