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

    // Expose header height so sticky elements can sit flush beneath it
    const setHeaderHeight = () => {
      document.documentElement.style.setProperty(
        "--header-h",
        `${header.offsetHeight}px`
      );
    };
    window.addEventListener("resize", setHeaderHeight);
    setHeaderHeight();
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

  // Poem archive: band filter + text search
  const archive = document.getElementById("poem-archive");
  if (archive) {
    const cards = Array.from(archive.querySelectorAll(".poem-leaf"));
    const buttons = Array.from(archive.querySelectorAll(".poem-filter__btn"));
    const input = archive.querySelector(".poem-search__input");
    const countEl = archive.querySelector(".poem-archive__count");
    const emptyEl = archive.querySelector(".poem-archive__empty");
    const haystack = new Map(cards.map((c) => [c, c.textContent.toLowerCase()]));
    let band = archive.querySelector(".poem-filter__btn.is-active").dataset.band;

    const apply = () => {
      const query = input.value.trim().toLowerCase();
      let shown = 0;

      cards.forEach((card) => {
        const visible =
          card.dataset.band === band &&
          (!query || haystack.get(card).includes(query));
        card.hidden = !visible;
        if (visible) shown += 1;
      });

      countEl.textContent = shown === 1 ? "1 Gedicht" : `${shown} Gedichte`;
      emptyEl.hidden = shown > 0;
    };

    // Title suggestions while typing (from the first letter on)
    const suggestions = archive.querySelector(".poem-search__suggestions");
    const titleOf = (card) =>
      card.querySelector(".poem__title").textContent.trim();

    const hideSuggestions = () => {
      if (!suggestions) return;
      suggestions.hidden = true;
      suggestions.innerHTML = "";
    };

    const showSuggestions = () => {
      if (!suggestions) return;
      const query = input.value.trim().toLowerCase();
      if (!query) {
        hideSuggestions();
        return;
      }

      const seen = new Set();
      const matches = [];
      cards.forEach((card) => {
        if (card.dataset.band !== band) return;
        const title = titleOf(card);
        const key = title.toLowerCase();
        if (seen.has(key) || !key.includes(query)) return;
        seen.add(key);
        matches.push(title);
      });

      if (!matches.length) {
        hideSuggestions();
        return;
      }

      suggestions.innerHTML = "";
      matches.slice(0, 6).forEach((title) => {
        const item = document.createElement("li");
        item.setAttribute("role", "option");
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "poem-search__suggestion";
        btn.textContent = title;
        btn.addEventListener("click", () => {
          input.value = title;
          apply();
          hideSuggestions();
          input.focus();
        });
        item.appendChild(btn);
        suggestions.appendChild(item);
      });
      suggestions.hidden = false;
    };

    if (suggestions) {
      input.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          hideSuggestions();
        } else if (event.key === "ArrowDown" && !suggestions.hidden) {
          event.preventDefault();
          suggestions.querySelector("button")?.focus();
        }
      });

      suggestions.addEventListener("keydown", (event) => {
        const items = Array.from(suggestions.querySelectorAll("button"));
        const index = items.indexOf(document.activeElement);
        if (event.key === "ArrowDown" && index < items.length - 1) {
          event.preventDefault();
          items[index + 1].focus();
        } else if (event.key === "ArrowUp") {
          event.preventDefault();
          if (index > 0) items[index - 1].focus();
          else input.focus();
        } else if (event.key === "Escape") {
          hideSuggestions();
          input.focus();
        }
      });

      document.addEventListener("click", (event) => {
        if (!event.target.closest(".poem-search")) hideSuggestions();
      });
    }

    const anchor = archive.querySelector(".poem-nav__anchor");

    buttons.forEach((btn) => {
      btn.addEventListener("click", () => {
        band = btn.dataset.band;
        hideSuggestions();
        buttons.forEach((other) => {
          const isActive = other === btn;
          other.classList.toggle("is-active", isActive);
          other.setAttribute("aria-selected", String(isActive));
        });
        apply();

        // Jump back to the nav so a shorter band never strands the reader past
        // the end of the list. Measured off the static anchor, since a stuck
        // sticky element reports its pinned position, not its natural one.
        const navTop = anchor.getBoundingClientRect().top + window.scrollY;
        const target = navTop - (header ? header.offsetHeight : 0);
        if (window.scrollY > target) {
          window.scrollTo({ top: target, behavior: "smooth" });
        }
      });
    });

    input.addEventListener("input", () => {
      apply();
      showSuggestions();
    });
    apply();
  }

  // Copyright year
  const yearEl = document.getElementById("copyright-year");
  if (yearEl) {
    yearEl.textContent = new Date().getFullYear();
  }

});
