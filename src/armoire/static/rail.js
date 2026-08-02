// Activity, blockers and registry issues. Collapsed by default: the graph is
// the product, and this is reference material you reach for deliberately.

function section(title) {
  const heading = document.createElement('h4');
  heading.textContent = title;
  return heading;
}

function list(items) {
  const ul = document.createElement('ul');
  for (const { text, className, onClick } of items) {
    const li = document.createElement('li');
    li.textContent = text;
    if (className) li.className = className;
    if (onClick) {
      li.style.cursor = 'pointer';
      li.addEventListener('click', onClick);
    }
    ul.append(li);
  }
  return ul;
}

export function initRail(toggle, panel, data, onOpen, signal) {
  const key = `armoire:rail:${data.root}`;
  const projects = data.projects || [];

  panel.replaceChildren();

  const byActivity = [...projects].sort((a, b) => b.commits - a.commits);
  panel.append(
    section('Activity · 30 days'),
    list(
      byActivity.map((p) => ({
        text: `${p.name} — ${p.commits}`,
        onClick: () => onOpen(p.name),
      })),
    ),
  );

  const blocked = projects.filter((p) => p.blocked_by.length > 0);
  panel.append(
    section(`Blocked · ${blocked.length} of ${projects.length}`),
    list(
      blocked.map((p) => ({
        text: `${p.name} ← ${p.blocked_by.join(', ')}`,
        onClick: () => onOpen(p.name),
      })),
    ),
  );

  if ((data.issues || []).length) {
    panel.append(
      section('Registry issues'),
      list(data.issues.map((text) => ({ text, className: 'issue' }))),
    );
  }

  function apply(open) {
    panel.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
    try {
      window.localStorage.setItem(key, open ? '1' : '0');
    } catch {
      /* storage unavailable; the toggle still works for this session */
    }
  }

  let open = false;
  try {
    open = window.localStorage.getItem(key) === '1';
  } catch {
    open = false;
  }
  apply(open);

  // `toggle` persists across every showRoadmap() call; without the signal
  // each revisit to the roadmap would stack another click listener on top of
  // the last, permanently.
  toggle.addEventListener(
    'click',
    () => {
      open = !open;
      apply(open);
    },
    { signal },
  );
}
