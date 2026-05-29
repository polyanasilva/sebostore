// ---------- Setas dos carrosséis temáticos da home ----------
document.querySelectorAll(".home-section").forEach((section) => {
  const scroller = section.querySelector(".home-section-scroll");
  if (!scroller) return;
  section.querySelectorAll(".similar-nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const dir = parseInt(btn.dataset.dir, 10) || 1;
      const card = scroller.querySelector(".similar-card");
      const step = card ? card.offsetWidth + 16 : 200;
      scroller.scrollBy({ left: step * dir * 2, behavior: "smooth" });
    });
  });
});

// ---------- Destaque rotativo (3 livros, troca um por vez) ----------
document.querySelectorAll(".spotlight").forEach((spotlight) => {
  const slides = spotlight.querySelectorAll(".spotlight-slide");
  const dots   = spotlight.querySelectorAll(".spotlight-dot");
  if (slides.length <= 1) return;

  let index = 0;
  const total = slides.length;
  const delay = parseInt(spotlight.dataset.autoplay, 10) || 6000;
  let timer = null;

  function show(i) {
    index = (i + total) % total;
    slides.forEach((s, k) => s.classList.toggle("is-active", k === index));
    dots.forEach((d, k)   => d.classList.toggle("is-active", k === index));
  }

  function next() { show(index + 1); }
  function prev() { show(index - 1); }

  function start() {
    stop();
    timer = setInterval(next, delay);
  }
  function stop() {
    if (timer) { clearInterval(timer); timer = null; }
  }

  spotlight.querySelectorAll(".spotlight-arrow").forEach((btn) => {
    btn.addEventListener("click", () => {
      const dir = parseInt(btn.dataset.dir, 10) || 1;
      dir > 0 ? next() : prev();
      start(); // reinicia o autoplay após interação
    });
  });

  dots.forEach((dot) => {
    dot.addEventListener("click", () => {
      show(parseInt(dot.dataset.index, 10) || 0);
      start();
    });
  });

  // Pausa quando o mouse está em cima
  spotlight.addEventListener("mouseenter", stop);
  spotlight.addEventListener("mouseleave", start);

  // Pausa quando a página não está visível (economiza CPU)
  document.addEventListener("visibilitychange", () => {
    document.hidden ? stop() : start();
  });

  start();
});

// ---------- Seta scroll suave do CTA do hero ----------
document.querySelectorAll('a[href^="#"]').forEach((link) => {
  link.addEventListener("click", (e) => {
    const targetId = link.getAttribute("href").slice(1);
    if (!targetId) return;
    const target = document.getElementById(targetId);
    if (!target) return;
    e.preventDefault();
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  });
});
