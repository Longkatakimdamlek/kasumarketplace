// hero-side-banners.js
// Generic auto-sliding carousel, used for both the vendor-promo banner and the
// spotlight-stores banner. Each banner just needs a track element with slides
// as direct children (each slide = full width of the track's container).

(function () {
  function initCarousel(trackId, dotsSelector, intervalMs) {
    const track = document.getElementById(trackId);
    if (!track) return;

    const slides = track.children;
    const totalSlides = slides.length;
    if (totalSlides <= 1) return; // nothing to slide

    const dots = document.querySelectorAll(dotsSelector);
    let current = 0;

    function goTo(index) {
      current = index;
      track.style.transform = `translateX(-${index * 100}%)`;
      dots.forEach((d, i) => {
        d.classList.toggle('opacity-100', i === index);
        d.classList.toggle('opacity-40', i !== index);
      });
    }

    let timer = setInterval(() => {
      goTo((current + 1) % totalSlides);
    }, intervalMs);

    // Pause on hover, resume on leave — nice touch for anyone reading a slide.
    track.parentElement.addEventListener('mouseenter', () => clearInterval(timer));
    track.parentElement.addEventListener('mouseleave', () => {
      timer = setInterval(() => goTo((current + 1) % totalSlides), intervalMs);
    });

    goTo(0);
  }

  document.addEventListener('DOMContentLoaded', () => {
    initCarousel('vendor-promo-track', '.vendor-promo-dot', 4500);
    initCarousel('spotlight-store-track', '.spotlight-store-dot', 5000);
  });
})();