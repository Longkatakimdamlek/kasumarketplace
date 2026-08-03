// hero-3d.js
// Three.js scene: a 3D shopping cart with generic 3D product models floating
// around/spilling out of it. Each item is mapped to a REAL featured product
// (name/price/url read from #hero-products-data) so hover/click still links
// to your actual catalog, even though the visual is a generic illustration.

(function () {
  if (typeof THREE === 'undefined') {
    console.warn('hero-3d.js: THREE.js not loaded, skipping hero 3D scene.');
    return;
  }
  if (typeof THREE.GLTFLoader === 'undefined') {
    console.warn('hero-3d.js: GLTFLoader not loaded, skipping hero 3D scene.');
    return;
  }

  const heroSection = document.getElementById('hero-3d');
  const canvas = document.getElementById('hero-canvas');
  const overlay = document.getElementById('hero-card-overlay');
  const dataEl = document.getElementById('hero-products-data');

  if (!heroSection || !canvas || !dataEl) return;
  if (window.innerWidth < 768) return; // desktop-only

  let products = [];
  try {
    products = JSON.parse(dataEl.textContent);
  } catch (e) {
    console.warn('hero-3d.js: could not parse product data', e);
    return;
  }

  // ---------- Model paths — ADJUST if your filenames/extensions differ ----------
  const MODEL_BASE = window.HERO_MODEL_BASE || '/static/marketplace/models/';
  const CART_MODEL = MODEL_BASE + 'shopping_cart.glb';
  const ITEM_MODELS = [
    MODEL_BASE + 't-shirt.glb',
    MODEL_BASE + 'female_bag.glb',
    MODEL_BASE + 'snack.glb',
    MODEL_BASE + 'shoe.glb',
    MODEL_BASE + 'sport_shoe.glb',
    MODEL_BASE + 'iphone_17_pro.glb',
    MODEL_BASE + 'macbook.glb'
  ];

  // ---------- Scene setup ----------
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(
    45,
    heroSection.clientWidth / heroSection.clientHeight,
    0.1,
    1000
  );
  camera.position.set(0, 1.5, 14);

  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(heroSection.clientWidth, heroSection.clientHeight);

  scene.add(new THREE.AmbientLight(0xffffff, 1.0));
  const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
  dirLight.position.set(3, 5, 6);
  scene.add(dirLight);
  const fillLight = new THREE.DirectionalLight(0xffffff, 0.3);
  fillLight.position.set(-4, 2, -3);
  scene.add(fillLight);

  const loader = new THREE.GLTFLoader();
  const cards = []; // interactive item roots (THREE.Group), each with userData.product

  function loadModel(url) {
    return new Promise((resolve, reject) => {
      loader.load(
        url,
        (gltf) => resolve(gltf.scene),
        undefined,
        (err) => reject(err)
      );
    });
  }

  // Normalize any loaded model to a consistent size, since source models
  // come in wildly different native scales.
  function normalizeScale(object3d, targetSize) {
    const box = new THREE.Box3().setFromObject(object3d);
    const size = new THREE.Vector3();
    box.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z) || 1;
    const scale = targetSize / maxDim;
    object3d.scale.setScalar(scale);

    // Re-center after scaling
    const centeredBox = new THREE.Box3().setFromObject(object3d);
    const center = new THREE.Vector3();
    centeredBox.getCenter(center);
    object3d.position.sub(center);
  }

  // ---------- Load the cart (decorative, not interactive) ----------
  const cartGroup = new THREE.Group();
  scene.add(cartGroup);

  loadModel(CART_MODEL)
    .then((cart) => {
      normalizeScale(cart, 6);
      cart.position.set(1.5, -1.8, 0);
      cart.rotation.y = -0.3;
      cartGroup.add(cart);
    })
    .catch((err) => {
      console.warn('hero-3d.js: failed to load cart model', CART_MODEL, err);
    });

  // ---------- Load item models, map each to a real product ----------
  // Positions arranged to look like items are spilling up and out of the cart basket.
  const itemSlots = [
    { x: 0.5, y: 1.2, z: 1.5 },
    { x: 2.0, y: 2.0, z: 1.0 },
    { x: 3.3, y: 1.0, z: 1.8 },
    { x: 1.2, y: 2.6, z: 0.2 },
    { x: 2.8, y: 2.4, z: -0.4 },
    { x: 0.2, y: 0.4, z: 2.2 },
    { x: 3.6, y: -0.2, z: 1.2 }
  ];

  const itemPromises = ITEM_MODELS.map((url, i) => {
    if (i >= products.length && products.length > 0) return null; // don't load more than we have products for
    return loadModel(url)
      .then((model) => {
        normalizeScale(model, 1.3);

        const root = new THREE.Group();
        root.add(model);

        const slot = itemSlots[i % itemSlots.length];
        root.position.set(slot.x, slot.y, slot.z);
        root.rotation.y = Math.random() * Math.PI * 2;

        const product = products[i % products.length] || null;

        root.userData = {
          product,
          phase: Math.random() * Math.PI * 2,
          bobSpeed: 0.4 + Math.random() * 0.3,
          baseY: slot.y,
          baseScale: root.scale.x || 1,
          hovered: false
        };
        // normalizeScale already applied to the child model, root itself stays at scale 1
        root.userData.baseScale = 1;

        scene.add(root);
        if (product) cards.push(root);
        return root;
      })
      .catch((err) => {
        console.warn('hero-3d.js: failed to load item model', url, err);
        return null;
      });
  });

  // ---------- Raycasting for hover/click ----------
  const raycaster = new THREE.Raycaster();
  const mouseNDC = new THREE.Vector2();
  let hoveredCard = null;

  function findCardRoot(object) {
    let o = object;
    while (o) {
      if (o.userData && o.userData.product) return o;
      o = o.parent;
    }
    return null;
  }

  function updatePointer(event) {
    const rect = heroSection.getBoundingClientRect();
    mouseNDC.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouseNDC.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  }

  function showOverlay(root, event) {
    const product = root.userData.product;
    overlay.innerHTML = `${product.name}<br><span style="color:#0f6b3d">${product.price}</span>`;
    const rect = heroSection.getBoundingClientRect();
    overlay.style.left = `${event.clientX - rect.left + 16}px`;
    overlay.style.top = `${event.clientY - rect.top - 16}px`;
    overlay.style.opacity = '1';
  }

  function hideOverlay() {
    overlay.style.opacity = '0';
  }

  heroSection.addEventListener('mousemove', (event) => {
    updatePointer(event);
    raycaster.setFromCamera(mouseNDC, camera);
    const intersects = raycaster.intersectObjects(cards, true);

    if (intersects.length > 0) {
      const root = findCardRoot(intersects[0].object);
      if (root && hoveredCard !== root) {
        if (hoveredCard) hoveredCard.userData.hovered = false;
        hoveredCard = root;
        hoveredCard.userData.hovered = true;
      }
      if (root) {
        showOverlay(root, event);
        canvas.style.cursor = 'pointer';
      }
    } else {
      if (hoveredCard) hoveredCard.userData.hovered = false;
      hoveredCard = null;
      hideOverlay();
      canvas.style.cursor = 'default';
    }
  });

  heroSection.addEventListener('mouseleave', () => {
    if (hoveredCard) hoveredCard.userData.hovered = false;
    hoveredCard = null;
    hideOverlay();
    canvas.style.cursor = 'default';
  });

  canvas.addEventListener('click', () => {
    if (hoveredCard && hoveredCard.userData.product && hoveredCard.userData.product.url) {
      window.location.href = hoveredCard.userData.product.url;
    }
  });

  // ---------- Camera parallax on mouse move ----------
  let camParallaxX = 0, camParallaxY = 0;
  heroSection.addEventListener('mousemove', (e) => {
    const rect = heroSection.getBoundingClientRect();
    camParallaxX = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
    camParallaxY = ((e.clientY - rect.top) / rect.height - 0.5) * 2;
  });

  // ---------- Render loop ----------
  let running = true;
  const clock = new THREE.Clock();

  function animate() {
    if (!running) return;
    requestAnimationFrame(animate);

    const t = clock.getElapsedTime();

    cards.forEach((root) => {
      const d = root.userData;
      if (!d.hovered) {
        root.position.y = d.baseY + Math.sin(t * d.bobSpeed + d.phase) * 0.25;
        root.rotation.y += 0.004;
        root.scale.setScalar(root.scale.x + (d.baseScale - root.scale.x) * 0.1);
      } else {
        root.scale.setScalar(root.scale.x + (d.baseScale * 1.25 - root.scale.x) * 0.15);
      }
    });

    cartGroup.rotation.y = Math.sin(t * 0.15) * 0.05;

    camera.position.x += (camParallaxX * 1.2 - camera.position.x) * 0.03;
    camera.position.y += (1.5 - camParallaxY * 0.6 - camera.position.y) * 0.03;
    camera.lookAt(2, 0.5, 0);

    renderer.render(scene, camera);
  }

  document.addEventListener('visibilitychange', () => {
    running = !document.hidden;
    if (running) animate();
  });

  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        running = entry.isIntersecting && !document.hidden;
        if (running) animate();
      });
    }, { threshold: 0.05 });
    observer.observe(heroSection);
  }

  window.addEventListener('resize', () => {
    if (window.innerWidth < 768) return;
    camera.aspect = heroSection.clientWidth / heroSection.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(heroSection.clientWidth, heroSection.clientHeight);
  });

  Promise.all(itemPromises).then(() => animate());
})();