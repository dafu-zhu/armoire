// Category colour, shared by the graph and the category column.
//
// A category's colour is assigned by insertion order rather than chosen by the
// registry author, so nothing in armoire.toml has to name a colour. That makes
// the *order map* the thing both renderers have to agree on, and neither of
// them sees every project: app.js splits the payload, handing the connected
// projects to renderRoadmap and the isolated ones to renderCategories. A map
// built inside either renderer would therefore number the same category
// differently on the two halves of one screen -- and usually not number it at
// all on the graph side, since a category whose only members are isolated
// never reaches renderRoadmap. Building it once, over the whole payload, and
// passing it to both is what makes "the container matches its category's node
// colour" (the spec's category column section) true rather than aspirational.

// cat-0..cat-4 are the five real fills; cat-5 is the uncategorised fallback and
// is never handed out by insertion order, hence CATEGORIES - 1 below.
export const CATEGORIES = 6;

export function categoryOrder(projects) {
  const order = new Map();
  for (const project of projects || []) categoryClass(project.category, order);
  return order;
}

export function categoryClass(category, order) {
  if (!category) return 'cat-5';
  if (!order.has(category)) order.set(category, order.size % (CATEGORIES - 1));
  return `cat-${order.get(category)}`;
}
