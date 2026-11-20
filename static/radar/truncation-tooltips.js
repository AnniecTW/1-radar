// Text cut off with an ellipsis (one line) or a line clamp (several lines) shows its full text as a tooltip on
// hover. Only when it is actually cut off: the check runs on each hover, so resizing the window is handled. An
// element's own title, set in a template, is left alone.
(() => {
  const MAX_DEPTH = 4; // How far up from the hovered element to look, e.g. a link inside a clamped heading.

  const cutOff = (el, style) => {
    if (style.textOverflow === 'ellipsis') return el.scrollWidth > el.clientWidth + 1;
    const clamp = style.webkitLineClamp || style.getPropertyValue('-webkit-line-clamp');
    if (clamp && clamp !== 'none') return el.scrollHeight > el.clientHeight + 1;
    return null; // Not an element that truncates.
  };

  document.addEventListener('mouseover', (event) => {
    let el = event.target instanceof Element ? event.target : null;
    for (let depth = 0; el && el !== document.body && depth < MAX_DEPTH; depth += 1, el = el.parentElement) {
      const clipped = cutOff(el, window.getComputedStyle(el));
      if (clipped === null) continue;
      const ours = 'autoTitle' in el.dataset;
      if (el.hasAttribute('title') && !ours) return;
      if (clipped) {
        el.title = el.textContent.replace(/\s+/g, ' ').trim();
        el.dataset.autoTitle = '';
      } else if (ours) {
        el.removeAttribute('title');
        delete el.dataset.autoTitle;
      }
      return;
    }
  });
})();
