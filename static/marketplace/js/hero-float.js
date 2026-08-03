(function () {
  const hero = document.getElementById('hero-3d');
  const container = document.getElementById('hero-floating-products');

  if (!hero || !container || window.innerWidth < 768) return;

  let targetX = 0;
  let targetY = 0;
  let currentX = 0;
  let currentY = 0;
  let rafId = null;
  let running = true;

  function updatePointer(event) {
    const rect = hero.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    const y = -(((event.clientY - rect.top) / rect.height) * 2 - 1);
    targetX = x;
    targetY = y;
  }

  function animate() {
    if (!running) return;

    currentX += (targetX - currentX) * 0.08;
    currentY += (targetY - currentY) * 0.08;

    container.style.setProperty('--mx', currentX.toFixed(3));
    container.style.setProperty('--my', currentY.toFixed(3));

    rafId = window.requestAnimationFrame(animate);
  }

  hero.addEventListener('mousemove', updatePointer);

  hero.addEventListener('mouseleave', () => {
    targetX = 0;
    targetY = 0;
  });

  document.addEventListener('visibilitychange', () => {
    running = !document.hidden;
    if (running) {
      if (rafId === null) {
        rafId = window.requestAnimationFrame(animate);
      }
    } else if (rafId !== null) {
      window.cancelAnimationFrame(rafId);
      rafId = null;
    }
  });

  if (running) {
    rafId = window.requestAnimationFrame(animate);
  }
})();
