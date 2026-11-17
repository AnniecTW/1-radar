document.addEventListener('DOMContentLoaded', () => {
  // Phone menu: the sidebar slides in as a drawer (sidebar.css). Above 620px the button is hidden.
  const sidebar = document.querySelector('.sidebar')
  const menuButton = document.querySelector('[data-sidebar-toggle]')
  const backdrop = document.querySelector('.sidebar-backdrop')
  if (sidebar && menuButton && backdrop) {
    const setMenuOpen = (open) => {
      document.body.classList.toggle('sidebar-open', open)
      backdrop.hidden = !open
      menuButton.setAttribute('aria-expanded', String(open))
      if (open) sidebar.querySelector('.nav a, .nav [tabindex]')?.focus()
      else menuButton.focus({ preventScroll: true })
    }
    const isMenuOpen = () => document.body.classList.contains('sidebar-open')
    menuButton.addEventListener('click', () => setMenuOpen(!isMenuOpen()))
    document.querySelectorAll('[data-sidebar-close]').forEach((element) => {
      element.addEventListener('click', () => setMenuOpen(false))
    })
    // Picking a page closes the drawer, including same-page anchors like Recommendations.
    sidebar.querySelectorAll('.nav a').forEach((link) => {
      link.addEventListener('click', () => { if (isMenuOpen()) setMenuOpen(false) })
    })
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && isMenuOpen()) setMenuOpen(false)
    })
    // Rotating to a wider screen shows the normal sidebar, so drop the drawer state.
    window.matchMedia('(min-width: 621px)').addEventListener('change', (query) => {
      if (query.matches && isMenuOpen()) {
        document.body.classList.remove('sidebar-open')
        backdrop.hidden = true
        menuButton.setAttribute('aria-expanded', 'false')
      }
    })
  }

  const profileMenu = document.querySelector('.profile-menu')
  if (profileMenu) {
    document.addEventListener('click', (event) => {
      if (!profileMenu.contains(event.target)) profileMenu.open = false
    })
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && profileMenu.open) {
        profileMenu.open = false
        profileMenu.querySelector('summary').focus()
      }
    })
  }

  const bio = document.querySelector('[data-counter]')
  if (bio) {
    const counter = document.getElementById(bio.dataset.counter)
    const updateCounter = () => { counter.textContent = `${bio.value.length} / ${bio.maxLength} characters` }
    bio.addEventListener('input', updateCounter)
    updateCounter()
  }

  const chips = document.getElementById('interest-chips')
  if (chips) {
    const count = document.getElementById('interest-count')
    const updateCount = () => {
      count.textContent = `${chips.querySelectorAll('input:checked').length} selected`
    }
    chips.addEventListener('change', updateCount)
    updateCount()
  }
})
