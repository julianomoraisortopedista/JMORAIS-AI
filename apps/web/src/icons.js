/** Inline SVG icons built with DOM APIs (no HTML parsing). */
const PATHS = /** @type {Record<string,string[]>} */ ({
  home: ['M3 10.5 12 3l9 7.5', 'M5 9.5V21h14V9.5', 'M10 21v-6h4v6'],
  user: ['M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z', 'M4 21a8 8 0 0 1 16 0'],
  search: ['M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Z', 'm20 20-4-4'],
  file: ['M14 3H6v18h12V7Z', 'M14 3v4h4', 'M9 12h6', 'M9 16h6'],
  upload: ['M12 16V4', 'm7 9 5-5 5 5', 'M4 20h16'],
});

/** @param {string} name @returns {SVGSVGElement} */
export function icon(name) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = /** @type {SVGSVGElement} */ (document.createElementNS(ns, 'svg'));
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('class', 'icon');
  for (const d of PATHS[name] || []) {
    const path = document.createElementNS(ns, 'path');
    path.setAttribute('d', d);
    svg.append(path);
  }
  return svg;
}
