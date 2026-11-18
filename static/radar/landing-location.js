// "Recommended for you" puts closer events higher once the user shares their location.
// Radar's banner explains why first; the browser's own prompt appears only after a tap on
// "Share location", because a "Block" there is usually permanent.
(() => {
  const DISMISS_KEY = 'radar.locationBannerDismissedAt';
  const DISMISS_DAYS = 30;
  const container = document.querySelector('[data-recommendations]');
  const banner = container && container.querySelector('[data-location-banner]');
  // No banner means the browser already sent a recent location (a six-hour cookie).
  if (!banner || !navigator.geolocation) return;

  const status = banner.querySelector('[data-location-status]');
  const shareButton = banner.querySelector('button[type="submit"]');

  // Remembering "Not now" is a per-browser convenience; if storage is blocked the banner just shows again.
  const recentlyDismissed = () => {
    try {
      return Date.now() - (Number(localStorage.getItem(DISMISS_KEY)) || 0) < DISMISS_DAYS * 86400000;
    } catch (error) {
      return false;
    }
  };
  const rememberDismissed = () => {
    try { localStorage.setItem(DISMISS_KEY, String(Date.now())); } catch (error) { /* storage blocked */ }
  };

  const getPosition = () => new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(
      (position) => resolve([position.coords.latitude, position.coords.longitude]),
      reject,
      { maximumAge: 300000, timeout: 10000 },
    );
  });

  // Sends the location, snapped to the ~500 m grid first (map-location.js) so the exact position never
  // leaves the device, then swaps in the re-ranked row and moves the map preview there.
  // A quiet refresh replaces the row the page just showed, so its impressions replace that row's too.
  const send = async (coords, { quiet }) => {
    const [lat, lng] = window.radarSnapLocation(coords);
    banner.elements.lat.value = lat;
    banner.elements.lng.value = lng;
    const body = new FormData(banner);
    if (quiet) body.append('replace', '1');
    const response = await fetch(banner.action, {
      method: 'POST', body, headers: { Accept: 'application/json' },
    });
    if (!response.ok) throw new Error(`Saving the location failed (${response.status})`);
    const data = await response.json();
    container.outerHTML = data.html;
    window.lucide?.createIcons();
    document.dispatchEvent(new CustomEvent('radar:location', { detail: [data.location.lat, data.location.lng] }));
  };

  const share = async ({ quiet }) => {
    try {
      await send(await getPosition(), { quiet });
    } catch (error) {
      if (quiet) return;
      if (error && error.code === 1) { banner.hidden = true; return; } // The user blocked it in the browser.
      status.hidden = false;
      status.textContent = 'Couldn’t get your location. Recommendations still work without it.';
      shareButton.disabled = false;
    }
  };

  banner.addEventListener('submit', (event) => {
    event.preventDefault();
    shareButton.disabled = true;
    share({ quiet: false });
  });
  banner.querySelector('[data-location-dismiss]').addEventListener('click', () => {
    rememberDismissed();
    banner.hidden = true;
  });
  // "Don't ask again" switches Account & privacy to "Don't use my location", so the two can't disagree.
  const neverButton = banner.querySelector('[data-location-never]');
  neverButton.addEventListener('click', async () => {
    neverButton.disabled = true;
    try {
      const response = await fetch(banner.dataset.offUrl, {
        method: 'POST', body: new FormData(banner), headers: { Accept: 'application/json' },
      });
      if (!response.ok) throw new Error(`Turning location off failed (${response.status})`);
      banner.querySelector('.location-actions').hidden = true;
      status.hidden = false;
      status.classList.add('is-note');
      status.textContent = 'Got it. Radar won’t use your location. You can turn it back on in Account & privacy.';
      window.setTimeout(() => { banner.hidden = true; }, 4000);
    } catch (error) {
      neverButton.disabled = false;
      status.hidden = false;
      status.textContent = 'Couldn’t save that. Please try again.';
    }
  });

  const decide = (state) => {
    if (state === 'granted') { share({ quiet: true }); return; } // Shared before: refresh without asking.
    if (state === 'denied') return; // Blocked in the browser: don't keep asking.
    if (!recentlyDismissed()) banner.hidden = false;
  };
  if (navigator.permissions?.query) {
    navigator.permissions.query({ name: 'geolocation' }).then((result) => decide(result.state), () => decide('prompt'));
  } else {
    decide('prompt');
  }
})();
