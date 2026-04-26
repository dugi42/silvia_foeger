document.addEventListener("DOMContentLoaded", () => {
  // Mobile nav toggle
  const navToggle = document.querySelector(".nav-toggle");
  const navLinks = document.querySelector(".nav-links");

  if (navToggle && navLinks) {
    navToggle.addEventListener("click", () => {
      const isOpen = navToggle.getAttribute("aria-expanded") === "true";
      navToggle.setAttribute("aria-expanded", String(!isOpen));
      navLinks.classList.toggle("is-open", !isOpen);
    });

    navLinks.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => {
        navToggle.setAttribute("aria-expanded", "false");
        navLinks.classList.remove("is-open");
      });
    });
  }

  // Scrolled header
  const header = document.getElementById("site-header");
  if (header) {
    const onScroll = () => {
      header.classList.toggle("scrolled", window.scrollY > 80);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  // Reveal on scroll
  const reveals = document.querySelectorAll(".reveal");
  if (reveals.length) {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.1, rootMargin: "0px 0px -40px 0px" }
    );
    reveals.forEach((el) => observer.observe(el));
  }

  // Copyright year
  const yearEl = document.getElementById("copyright-year");
  if (yearEl) {
    yearEl.textContent = new Date().getFullYear();
  }

  // Booklet / poem carousel — inject washi tape into each leaf
  document.querySelectorAll(".poem-leaf").forEach((leaf) => {
    const tape = document.createElement("div");
    tape.className = "poem__tape";
    tape.setAttribute("aria-hidden", "true");
    leaf.appendChild(tape);
  });

  const bookletTrack = document.getElementById("booklet-track");
  if (bookletTrack) {
    const pages = bookletTrack.querySelectorAll(".booklet__page");
    const dotsEl = document.getElementById("booklet-dots");
    const counterEl = document.getElementById("booklet-counter");
    const prevBtn = document.querySelector(".booklet__btn--prev");
    const nextBtn = document.querySelector(".booklet__btn--next");
    const total = pages.length;
    let current = 0;

    pages.forEach((_, i) => {
      const dot = document.createElement("button");
      dot.className = "booklet__dot";
      dot.setAttribute("aria-label", `Gedicht ${i + 1}`);
      dot.setAttribute("role", "tab");
      dot.addEventListener("click", () => goTo(i));
      dotsEl.appendChild(dot);
    });

    function update() {
      bookletTrack.style.transform = `translateX(-${current * 100}%)`;
      dotsEl.querySelectorAll(".booklet__dot").forEach((d, i) => {
        d.classList.toggle("is-active", i === current);
        d.setAttribute("aria-selected", String(i === current));
      });
      if (counterEl) counterEl.textContent = `${current + 1} / ${total}`;
      if (prevBtn) prevBtn.disabled = current === 0;
      if (nextBtn) nextBtn.disabled = current === total - 1;
    }

    function goTo(n) {
      current = Math.max(0, Math.min(total - 1, n));
      update();
    }

    prevBtn?.addEventListener("click", () => goTo(current - 1));
    nextBtn?.addEventListener("click", () => goTo(current + 1));

    // Keyboard navigation (only when booklet is in focus area)
    bookletTrack.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") { e.preventDefault(); goTo(current - 1); }
      if (e.key === "ArrowRight") { e.preventDefault(); goTo(current + 1); }
    });

    // Touch / swipe
    let touchStartX = 0;
    bookletTrack.addEventListener("touchstart", (e) => {
      touchStartX = e.touches[0].clientX;
    }, { passive: true });
    bookletTrack.addEventListener("touchend", (e) => {
      const delta = touchStartX - e.changedTouches[0].clientX;
      if (Math.abs(delta) > 40) goTo(delta > 0 ? current + 1 : current - 1);
    }, { passive: true });

    update();
  }
});
