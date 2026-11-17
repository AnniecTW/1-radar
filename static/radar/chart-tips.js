// Hover tips for the host analytics charts: any element with data-tip shows its text
// in one small tooltip that follows the pointer, and on keyboard focus sits above the element.
(() => {
  const tip = document.createElement('div');
  tip.className = 'chart-tip';
  tip.setAttribute('aria-hidden', 'true');
  document.body.appendChild(tip);
  let current = null;

  function place(x, y) {
    const half = tip.offsetWidth / 2;
    tip.style.left = Math.min(Math.max(x, half + 8), window.innerWidth - half - 8) + 'px';
    const below = y - tip.offsetHeight - 14 < 8;
    tip.classList.toggle('below', below);
    tip.style.top = y + 'px';
  }

  function show(el, x, y) {
    if (el !== current) {
      tip.textContent = el.dataset.tip;
      current = el;
    }
    tip.classList.add('show');
    if (x === undefined) {
      const box = el.getBoundingClientRect();
      x = box.left + box.width / 2;
      y = box.top;
    }
    place(x, y);
  }

  function hide() {
    tip.classList.remove('show');
    current = null;
  }

  function onPointer(event) {
    const el = event.target.closest && event.target.closest('[data-tip]');
    if (el) show(el, event.clientX, event.clientY);
    else if (current) hide();
  }

  document.addEventListener('pointermove', onPointer);
  document.addEventListener('pointerdown', onPointer);
  document.addEventListener('pointerleave', hide);
  document.addEventListener('focusin', (event) => {
    const el = event.target.closest && event.target.closest('[data-tip]');
    if (el) show(el);
  });
  document.addEventListener('focusout', hide);
  window.addEventListener('scroll', hide, { passive: true });
})();
