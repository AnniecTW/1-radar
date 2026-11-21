// "Not interested" on Recommended cards (FR-43). The dismissal is sent straight away and the card leaves the
// row, closing the gap. "Hidden. Undo" stays for about 8 seconds (longer while hovered or focused); Undo
// reverses the dismissal and puts the card back where it was. No replacement is fetched: the next page load
// shows a full row again, with similar events ranked lower. Without JavaScript the form posts normally.
(() => {
  const TOAST_MS = 8000;
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const toast = document.createElement('div');
  toast.className = 'rec-toast';
  toast.setAttribute('role', 'status');
  toast.hidden = true;
  const message = document.createElement('span');
  const undoButton = document.createElement('button');
  undoButton.type = 'button';
  undoButton.textContent = 'Undo';
  toast.append(message, undoButton);
  document.body.append(toast);

  let pending = null; // The last dismissal that can still be undone: { form, card, row, before, empty }.
  let timer = null;

  const post = (form, extra) => {
    const body = new FormData(form);
    Object.entries(extra || {}).forEach(([key, value]) => body.append(key, value));
    return fetch(form.action, { method: 'POST', body, headers: { Accept: 'application/json' } }).then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
    });
  };

  const hideToast = () => {
    window.clearTimeout(timer);
    const hadFocus = toast.contains(document.activeElement);
    toast.hidden = true;
    pending = null;
    // Don't leave keyboard focus on a button that just disappeared.
    if (hadFocus) document.querySelector('#recommendations [data-row] .event-card h3 a, #recommendations-title')?.focus();
  };
  const startTimer = () => { window.clearTimeout(timer); timer = window.setTimeout(hideToast, TOAST_MS); };
  toast.addEventListener('mouseenter', () => window.clearTimeout(timer));
  toast.addEventListener('mouseleave', startTimer);
  toast.addEventListener('focusin', () => window.clearTimeout(timer));
  toast.addEventListener('focusout', startTimer);

  const showToast = (text, { undo }) => {
    message.textContent = text;
    undoButton.hidden = !undo;
    toast.hidden = false;
    startTimer();
  };

  // Take the card out, or put it back exactly where it was. A row with no cards left says so.
  const removeCard = ({ card, row, section }) => {
    card.remove();
    if (!row.querySelector('.event-card')) {
      row.hidden = true;
      const empty = document.createElement('p');
      empty.className = 'empty';
      empty.dataset.recommendationsEmpty = '';
      empty.textContent = 'Nothing left here for now.';
      row.after(empty);
    }
  };
  const restoreCard = ({ card, row, before, section }) => {
    row.hidden = false;
    section.querySelector('[data-recommendations-empty]')?.remove();
    card.classList.remove('is-leaving');
    card.querySelector('.dismiss').disabled = false;
    row.insertBefore(card, before && before.parentNode === row ? before : null);
  };

  document.addEventListener('submit', async (event) => {
    const form = event.target.closest('form[data-dismiss-recommendation]');
    if (!form) return;
    event.preventDefault();
    const button = form.querySelector('.dismiss');
    const card = form.closest('.event-card');
    const row = card.closest('[data-row]');
    const section = card.closest('.section');
    const viaKeyboard = button.matches(':focus-visible');
    const spot = { form, card, row, section, before: card.nextElementSibling };
    button.disabled = true;
    card.classList.add('is-leaving');
    try {
      await Promise.all([post(form), new Promise((done) => window.setTimeout(done, reducedMotion ? 0 : 180))]);
    } catch (error) {
      restoreCard(spot);
      showToast('Couldn’t hide that event. Please try again.', { undo: false });
      return;
    }
    removeCard(spot);
    pending = spot;
    showToast('Hidden. You’ll see fewer events like this.', { undo: true });
    if (viaKeyboard) undoButton.focus();
  });

  undoButton.addEventListener('click', async () => {
    const spot = pending;
    if (!spot) return;
    undoButton.disabled = true;
    try {
      await post(spot.form, { undo: '1' });
      hideToast();
      // Sharing a location swaps in a freshly ranked row; then the event simply comes back on the next load.
      if (document.contains(spot.row)) {
        restoreCard(spot);
        spot.card.querySelector('.dismiss').focus({ preventScroll: true });
      }
    } catch (error) {
      showToast('Couldn’t undo that. Please try again.', { undo: true });
    } finally {
      undoButton.disabled = false;
    }
  });
})();
