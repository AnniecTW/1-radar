// Hero carousel: the background photo and its caption card change together every 6 s.
// Pauses on hover/focus, and stays still for people who prefer reduced motion.
document.querySelectorAll('.hero-carousel').forEach((carousel) => {
  const slides = [...carousel.querySelectorAll('.carousel-slide')];
  const captions = [...carousel.querySelectorAll('.hero-caption')];
  const dots = [...carousel.querySelectorAll('.carousel-dot')];
  if (slides.length < 2) return;

  let current = 0;
  let timer;
  const show = (index) => {
    current = (index + slides.length) % slides.length;
    slides.forEach((slide, i) => slide.classList.toggle('is-active', i === current));
    captions.forEach((caption, i) => {
      caption.classList.toggle('is-active', i === current);
      caption.hidden = i !== current;
    });
    dots.forEach((dot, i) => {
      dot.classList.toggle('is-active', i === current);
      dot.setAttribute('aria-current', String(i === current));
    });
  };
  const stop = () => window.clearInterval(timer);
  const start = () => {
    stop();
    if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      timer = window.setInterval(() => show(current + 1), 6000);
    }
  };

  carousel.querySelector('.previous').addEventListener('click', () => { show(current - 1); start(); });
  carousel.querySelector('.next').addEventListener('click', () => { show(current + 1); start(); });
  dots.forEach((dot, i) => dot.addEventListener('click', () => { show(i); start(); }));
  carousel.addEventListener('mouseenter', stop);
  carousel.addEventListener('mouseleave', start);
  carousel.addEventListener('focusin', stop);
  carousel.addEventListener('focusout', (event) => {
    if (!carousel.contains(event.relatedTarget)) start();
  });
  document.addEventListener('visibilitychange', () => (document.hidden ? stop() : start()));
  start();
});

// Category chips stay on one line: chips that don't fit fold into "More", last first.
// Phones scroll the row sideways instead, so nothing folds there.
const categoryRow = document.querySelector('[data-category-row]');
const moreMenu = categoryRow && categoryRow.querySelector('.chip-more');
if (categoryRow && moreMenu) {
  const phoneQuery = window.matchMedia('(max-width: 760px)');
  const foldableChips = [...categoryRow.querySelectorAll(':scope > .chip[data-slug]')];
  const menuEntryFor = (chip) => moreMenu.querySelector(`.chip-menu-list a[data-slug="${chip.dataset.slug}"]`);
  const alwaysInMenu = moreMenu.querySelectorAll('.chip-menu-list a:not([data-slug])').length;

  const fitChips = () => {
    foldableChips.forEach((chip) => { chip.hidden = false; menuEntryFor(chip).hidden = true; });
    moreMenu.hidden = false;
    if (!phoneQuery.matches) {
      const firstLineTop = categoryRow.firstElementChild.offsetTop;
      const wraps = () => moreMenu.offsetTop > firstLineTop;
      for (let i = foldableChips.length - 1; i >= 0 && wraps(); i -= 1) {
        const chip = foldableChips[i];
        if (chip.classList.contains('selected')) continue; // keep the active filter visible
        chip.hidden = true;
        menuEntryFor(chip).hidden = false;
      }
    }
    const folded = foldableChips.filter((chip) => chip.hidden).length;
    moreMenu.hidden = folded + alwaysInMenu === 0;
  };

  let resizeFrame;
  window.addEventListener('resize', () => {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(fitChips);
  });
  // Icons and web fonts change chip widths, so measure again once they are in.
  fitChips();
  window.addEventListener('DOMContentLoaded', () => requestAnimationFrame(fitChips));
  document.fonts?.ready.then(fitChips);

  // Close on outside click, the sheet's backdrop or close button, Escape, or picking a category.
  document.addEventListener('click', (event) => {
    if (!moreMenu.open) return;
    const onBackdrop = event.target === moreMenu;
    if (onBackdrop || !moreMenu.contains(event.target) || event.target.closest('.chip-menu-close')) moreMenu.open = false;
  });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') moreMenu.open = false; });
}

// Card rows (e.g. Recommended for you) use the same card width as the All upcoming events grid.
const browseGrid = document.querySelector('#browse .event-grid');
const homeMain = document.querySelector('.home-main');
if (browseGrid && homeMain) {
  const syncCardWidth = () => {
    const columnWidth = parseFloat(getComputedStyle(browseGrid).gridTemplateColumns);
    if (columnWidth) homeMain.style.setProperty('--grid-card-width', `${columnWidth}px`);
  };
  new ResizeObserver(syncCardWidth).observe(browseGrid);
  syncCardWidth();
}

document.querySelectorAll('[data-scroll]').forEach((button) => {
  button.addEventListener('click', () => {
    const row = button.closest('.section').querySelector('[data-row]');
    row.scrollBy({ left: Number(button.dataset.scroll) * row.clientWidth * 0.8, behavior: 'smooth' });
  });
});

const mapElement = document.getElementById('map-preview');
if (mapElement && window.L) {
  const points = JSON.parse(document.getElementById('map-points').textContent);
  const center = JSON.parse(document.getElementById('map-center').textContent) || [40.102, -88.2272];
  const map = L.map(mapElement, { scrollWheelZoom: false }).setView(center, 15);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map);
  if (points.length && L.heatLayer) {
    const maxWeight = Math.max(...points.map((point) => point.weight));
    L.heatLayer(points.map((point) => [point.lat, point.lng, point.weight / maxWeight]), {
      radius: 32,
      blur: 24,
    }).addTo(map);
  }
  const escapeHtml = (text) => text.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const popupHtml = (point) => {
    const when = new Date(point.start).toLocaleString([], { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
    return `<a class="map-popup" href="/events/${encodeURIComponent(point.slug)}/"><b>${escapeHtml(point.title)}</b>`
      + `<small>${escapeHtml(point.place)}</small><small>${escapeHtml(when)}</small></a>`;
  };
  let busiest = null;
  points.forEach((point) => {
    const marker = L.circleMarker([point.lat, point.lng], { radius: 6, color: '#fff', weight: 2, fillColor: '#c65024', fillOpacity: 1 })
      .bindPopup(popupHtml(point), { closeButton: false, offset: [0, -4] })
      .addTo(map);
    if (!busiest || point.weight > busiest.point.weight) busiest = { point, marker };
  });
  // Show the most popular event straight away, like a preview of what the full map offers.
  if (busiest) busiest.marker.openPopup();
}
