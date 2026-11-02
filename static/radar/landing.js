// Sign-in prompt: guests tapping RSVP, Save or Follow get a dialog, never the action (FR-52).
const dialog = document.getElementById('signin-dialog');
const message = document.getElementById('signin-message');
const signinLink = document.getElementById('signin-link');
const signupLink = document.getElementById('signup-link');

document.addEventListener('click', (event) => {
  const trigger = event.target.closest('[data-gate]');
  if (!trigger) return;
  message.textContent = trigger.dataset.prompt;
  // Return to the exact page, filters and scroll anchor after authenticating.
  const next = encodeURIComponent(location.pathname + location.search + location.hash);
  signinLink.href = `${signinLink.dataset.base ||= signinLink.getAttribute('href')}?next=${next}`;
  signupLink.href = `${signupLink.dataset.base ||= signupLink.getAttribute('href')}?next=${next}`;
  dialog.showModal();
});

// Clicking the backdrop dismisses the prompt and leaves the guest where they were.
dialog.addEventListener('click', (event) => {
  if (event.target === dialog) dialog.close();
});

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
  points.forEach((point) => {
    L.circleMarker([point.lat, point.lng], { radius: 5, color: '#fff', weight: 2, fillColor: '#c65024', fillOpacity: 1 })
      .bindTooltip(point.title)
      .addTo(map);
  });
}
