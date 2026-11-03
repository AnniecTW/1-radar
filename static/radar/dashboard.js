document.addEventListener('DOMContentLoaded', () => {
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
  document.querySelectorAll('.chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('.chip').forEach((item) => item.classList.remove('selected'))
      chip.classList.add('selected')
    })
  })
  document.querySelectorAll('.save').forEach((button) => {
    button.addEventListener('click', () => {
      button.classList.toggle('saved')
      button.textContent = button.classList.contains('saved') ? '♥' : '♡'
      button.setAttribute('aria-label', button.classList.contains('saved') ? 'Event saved' : 'Save event')
    })
  })
  document.querySelectorAll('.rsvp').forEach((button) => {
    button.addEventListener('click', () => {
      button.textContent = button.textContent === 'RSVP' ? 'Going' : 'RSVP'
      button.classList.toggle('confirmed')
    })
  })

  document.querySelectorAll('.carousel').forEach((carousel) => {
    const slides = [...carousel.querySelectorAll('.carousel-slide')]
    const dots = [...carousel.querySelectorAll('.carousel-dot')]
    if (slides.length < 2) return

    let current = 0
    let timer
    const show = (index) => {
      current = (index + slides.length) % slides.length
      slides.forEach((slide, i) => {
        const active = i === current
        slide.classList.toggle('is-active', active)
        slide.setAttribute('aria-hidden', String(!active))
      })
      dots.forEach((dot, i) => {
        const active = i === current
        dot.classList.toggle('is-active', active)
        dot.setAttribute('aria-current', String(active))
      })
    }
    const stop = () => window.clearInterval(timer)
    const start = () => {
      stop()
      if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        timer = window.setInterval(() => show(current + 1), 6000)
      }
    }

    carousel.querySelector('.previous').addEventListener('click', () => { show(current - 1); start() })
    carousel.querySelector('.next').addEventListener('click', () => { show(current + 1); start() })
    dots.forEach((dot, i) => dot.addEventListener('click', () => { show(i); start() }))
    carousel.addEventListener('mouseenter', stop)
    carousel.addEventListener('mouseleave', start)
    carousel.addEventListener('focusin', stop)
    carousel.addEventListener('focusout', (event) => {
      if (!carousel.contains(event.relatedTarget)) start()
    })
    document.addEventListener('visibilitychange', () => document.hidden ? stop() : start())
    start()
  })
})
