// hero-background.js
// Layered CSS gradient + 2D-canvas particle field behind the hero's Three.js scene.
// Fully independent of hero-3d.js — safe to retune colors/particle count here
// without touching any WebGL code.

(function () {
  const heroSection = document.getElementById('hero-3d');
  if (!heroSection) return; // not on this page

  // Desktop-only: this hero section is inside a `.hidden.md:block` wrapper anyway,
  // but bail early on narrow viewports to avoid wasted work.
  if (window.innerWidth < 768) return;

  // ---------- Animated gradient mesh (CSS-driven) ----------
  const gradientEl = document.getElementById('hero-gradient');
  if (gradientEl) {
    gradientEl.style.background = `
      radial-gradient(circle at 20% 30%, rgba(15,107,61,0.85) 0%, transparent 55%),
      radial-gradient(circle at 80% 20%, rgba(3,106,61,0.75) 0%, transparent 50%),
      radial-gradient(circle at 60% 80%, rgba(10,77,42,0.8) 0%, transparent 55%),
      linear-gradient(135deg, #0f6b3d 0%, #0a4d2a 100%)
    `;
    gradientEl.style.backgroundSize = '180% 180%, 160% 160%, 200% 200%, 100% 100%';
    gradientEl.style.willChange = 'transform, background-position';

    // Slow drifting loop via CSS animation (keyframes injected once, globally).
    if (!document.getElementById('hero-gradient-keyframes')) {
      const style = document.createElement('style');
      style.id = 'hero-gradient-keyframes';
      style.textContent = `
        @keyframes heroGradientDrift {
          0%   { background-position: 0% 0%, 100% 0%, 50% 100%, 0% 0%; }
          50%  { background-position: 30% 40%, 70% 30%, 60% 70%, 0% 0%; }
          100% { background-position: 0% 0%, 100% 0%, 50% 100%, 0% 0%; }
        }
      `;
      document.head.appendChild(style);
    }
    gradientEl.style.animation = 'heroGradientDrift 22s ease-in-out infinite';
  }

  // ---------- Particle field (plain 2D canvas, not WebGL) ----------
  const canvas = document.getElementById('particle-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  let particles = [];
  const PARTICLE_COUNT = 50;

  function resize() {
    const rect = heroSection.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;
  }

  function makeParticle() {
    return {
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      r: Math.random() * 2 + 1,
      speedY: Math.random() * 0.3 + 0.1,
      speedX: (Math.random() - 0.5) * 0.15,
      opacity: Math.random() * 0.5 + 0.15
    };
  }

  function initParticles() {
    particles = [];
    for (let i = 0; i < PARTICLE_COUNT; i++) particles.push(makeParticle());
  }

  // Mouse parallax target, lerped each frame for smoothness.
  let mouseX = 0, mouseY = 0;
  let parallaxX = 0, parallaxY = 0;

  heroSection.addEventListener('mousemove', (e) => {
    const rect = heroSection.getBoundingClientRect();
    mouseX = ((e.clientX - rect.left) / rect.width - 0.5) * 2;  // -1..1
    mouseY = ((e.clientY - rect.top) / rect.height - 0.5) * 2;  // -1..1
  });

  heroSection.addEventListener('mouseleave', () => {
    mouseX = 0;
    mouseY = 0;
  });

  let running = true;

  function draw() {
    if (!running) return;

    // Lerp parallax toward mouse target.
    parallaxX += (mouseX - parallaxX) * 0.04;
    parallaxY += (mouseY - parallaxY) * 0.04;

    // Apply subtle parallax to the gradient layer via transform.
    if (gradientEl) {
      gradientEl.style.transform = `translate(${parallaxX * 15}px, ${parallaxY * 15}px)`;
    }

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.globalCompositeOperation = 'lighter';

    particles.forEach((p) => {
      p.y -= p.speedY;
      p.x += p.speedX;

      if (p.y < -10) {
        p.y = canvas.height + 10;
        p.x = Math.random() * canvas.width;
      }
      if (p.x < -10) p.x = canvas.width + 10;
      if (p.x > canvas.width + 10) p.x = -10;

      const drawX = p.x + parallaxX * 20;
      const drawY = p.y + parallaxY * 20;

      const gradient = ctx.createRadialGradient(drawX, drawY, 0, drawX, drawY, p.r * 4);
      gradient.addColorStop(0, `rgba(255,255,255,${p.opacity})`);
      gradient.addColorStop(1, 'rgba(255,255,255,0)');

      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.arc(drawX, drawY, p.r * 4, 0, Math.PI * 2);
      ctx.fill();
    });

    ctx.globalCompositeOperation = 'source-over';
    requestAnimationFrame(draw);
  }

  // Pause when tab hidden or hero scrolled out of view.
  document.addEventListener('visibilitychange', () => {
    running = !document.hidden;
    if (running) requestAnimationFrame(draw);
  });

  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        running = entry.isIntersecting && !document.hidden;
        if (running) requestAnimationFrame(draw);
      });
    }, { threshold: 0.05 });
    observer.observe(heroSection);
  }

  window.addEventListener('resize', () => {
    resize();
    initParticles();
  });

  resize();
  initParticles();
  requestAnimationFrame(draw);
})();