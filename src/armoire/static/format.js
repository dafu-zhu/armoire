// Shared by the directory listing and the status bar so a file reports the
// same size and age in both places.

export function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

export function formatAge(mtime) {
  const days = (Date.now() / 1000 - mtime) / 86400;
  if (days < 1) return 'today';
  if (days < 2) return 'yesterday';
  if (days < 30) return `${Math.floor(days)} days ago`;
  if (days < 365) return `${Math.floor(days / 30)} months ago`;
  return `${Math.floor(days / 365)} years ago`;
}

// Every write to location.hash -- navigate(), the breadcrumb links, and a
// rendered markdown file's relative links -- must go through this. A raw "%"
// or other reserved character in a path segment is not a valid
// percent-escape, and currentPath()'s decodeURIComponent throws on it.
export function encodeHashPath(path) {
  // Encode per segment: the separators are structural and must survive.
  return path.split('/').map(encodeURIComponent).join('/');
}
