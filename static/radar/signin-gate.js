// Guest sign-in prompt, shared by the home page and Explore Map (templates/discovery/_signin_dialog.html).
(() => {
// Sign-in prompt: guests tapping RSVP, Save or Follow get a dialog, never the action (FR-52).
// Signed-in users have no dialog on the page; their buttons do the real thing.
const dialog = document.getElementById('signin-dialog');
if (dialog) {
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
}
})();
