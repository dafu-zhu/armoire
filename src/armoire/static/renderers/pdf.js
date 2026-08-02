export function renderPdf(container, data, path) {
  const frame = document.createElement('iframe');
  frame.className = 'pdf';
  frame.src = `/api/raw?path=${encodeURIComponent(path)}`;
  container.append(frame);
  return 'pdf';
}
