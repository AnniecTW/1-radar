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

// Delegated, so rows swapped in later (Recommended for you, after sharing a location) scroll too.
document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-scroll]');
  if (!button) return;
  const row = button.closest('.section').querySelector('[data-row]');
  row.scrollBy({ left: Number(button.dataset.scroll) * row.clientWidth * 0.8, behavior: 'smooth' });
});

const mapElement = document.getElementById('map-preview');
if (mapElement && window.maplibregl && mapElement.dataset.maptilerKey) {
  const points = JSON.parse(document.getElementById('map-points').textContent);
  const userLocationScript = document.getElementById('user-location');
  const userLocation = userLocationScript ? JSON.parse(userLocationScript.textContent) : null;
  const center = (Array.isArray(userLocation) && userLocation)
    || JSON.parse(document.getElementById('map-center').textContent) || [40.102, -88.2272];
  // Same MapTiler style as the Explore Map.
  const map = new maplibregl.Map({
    container: mapElement,
    style: `https://api.maptiler.com/maps/streets-v2/style.json?key=${encodeURIComponent(mapElement.dataset.maptilerKey)}`,
    center: [center[1], center[0]],
    zoom: 14.5,
    scrollZoom: false,
    attributionControl: { compact: true },
  });
  new ResizeObserver(() => map.resize()).observe(mapElement);

  // Popularity heatmap, styled like the Explore Map's.
  const maxWeight = Math.max(1, ...points.map((point) => point.weight));
  map.on('load', () => {
    map.addSource('event-heat', {
      type: 'geojson',
      data: {
        type: 'FeatureCollection',
        features: points.map((point) => ({
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [point.lng, point.lat] },
          properties: { weight: 0.4 + 0.6 * (point.weight / maxWeight) },
        })),
      },
    });
    map.addLayer({
      id: 'event-heat',
      type: 'heatmap',
      source: 'event-heat',
      paint: {
        'heatmap-weight': ['get', 'weight'],
        'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 10, 1.6, 16, 3],
        'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 10, 30, 13, 55, 16, 90],
        'heatmap-opacity': 0.75,
        'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'],
          0, 'rgba(255,253,249,0)', 0.08, 'rgba(150,190,230,0.5)', 0.3, 'rgba(244,210,110,0.72)',
          0.55, 'rgba(240,140,75,0.82)', 0.85, 'rgba(198,80,36,0.9)'],
      },
    });
  });

  const popupContent = (point) => {
    const popup = document.createElement('a');
    popup.className = 'map-popup';
    popup.href = `/events/${encodeURIComponent(point.slug)}/`;
    const title = document.createElement('b');
    title.textContent = point.title;
    const where = document.createElement('small');
    where.textContent = point.place;
    const when = document.createElement('small');
    when.textContent = new Date(point.start).toLocaleString([], { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
    popup.append(title, where, when);
    return popup;
  };
  let busiest = null;
  points.forEach((point) => {
    const dot = document.createElement('div');
    dot.className = 'map-dot';
    const marker = new maplibregl.Marker({ element: dot })
      .setLngLat([point.lng, point.lat])
      .setPopup(new maplibregl.Popup({ offset: 10, closeButton: false }).setDOMContent(popupContent(point)))
      .addTo(map);
    if (!busiest || point.weight > busiest.point.weight) busiest = { point, marker };
  });
  // An "approximate location" circle (map-location.js) once the user shares their location
  // (landing-location.js), or if they shared it recently anywhere in Radar. It replaces the busiest-event popup.
  let approximate = null;
  const showUserLocation = ([lat, lng]) => {
    approximate?.remove();
    approximate = window.radarApproximateLocation(map, [lat, lng]);
    mapElement.setAttribute('aria-label', 'Heat map of upcoming campus events, with a shaded circle around your approximate location');
    map.easeTo({ center: [lng, lat] });
  };
  document.addEventListener('radar:location', (event) => showUserLocation(event.detail));
  if (Array.isArray(userLocation)) showUserLocation(userLocation);
  // Show the most popular event straight away, like a preview of what the full map offers.
  else if (busiest) map.once('load', () => busiest.marker.togglePopup());
}
