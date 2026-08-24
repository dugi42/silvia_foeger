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
    const listItems = Array.from(archive.querySelector(".poems-list").children);
    const buttons = Array.from(archive.querySelectorAll(".poem-filter__btn"));
    const input = archive.querySelector(".poem-search__input");
    const countEl = archive.querySelector(".poem-archive__count");
    const emptyEl = archive.querySelector(".poem-archive__empty");
    const haystack = new Map(cards.map((c) => [c, c.textContent.toLowerCase()]));
    let band = archive.querySelector(".poem-filter__btn.is-active").dataset.band;

    // Both the site header and the band nav are sticky, so a heading has to
    // clear their combined height to stay readable after the jump.
    const stickyNav = archive.querySelector(".poem-nav");
    const scrollToHeading = (headingEl) => {
      const offset =
        (header ? header.offsetHeight : 0) +
        (stickyNav ? stickyNav.offsetHeight : 0) +
        16;
      const top = headingEl.getBoundingClientRect().top + window.scrollY - offset;
      window.scrollTo({ top, behavior: "smooth" });
    };

    // Table of contents, built from the group headings so both stay in sync
    const toc = archive.querySelector(".poem-toc");
    const tocLinks = new Map();
    if (toc) {
      const list = toc.querySelector(".poem-toc__list");
      listItems
        .filter((el) => el.classList.contains("poem-group"))
        .forEach((headingEl) => {
          const item = document.createElement("li");
          const link = document.createElement("a");
          link.className = "poem-toc__link";
          link.href = `#${headingEl.id}`;
          link.textContent = headingEl.textContent;
          link.addEventListener("click", (event) => {
            event.preventDefault();
            scrollToHeading(headingEl);
          });
          item.appendChild(link);
          list.appendChild(item);
          tocLinks.set(headingEl, item);
        });
    }

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

      // A group heading stays only as long as a poem below it survived the
      // filter, so empty themes disappear along with their poems.
      let heading = null;
      let headingHasPoem = false;
      let themes = 0;
      const settle = () => {
        if (!heading) return;
        heading.hidden = !headingHasPoem;
        const item = tocLinks.get(heading);
        if (item) item.hidden = !headingHasPoem;
        if (headingHasPoem) themes += 1;
      };

      listItems.forEach((el) => {
        if (el.classList.contains("poem-group")) {
          settle();
          heading = el;
          headingHasPoem = false;
        } else if (el.dataset.group && !el.hidden) {
          headingHasPoem = true;
        }
      });
      settle();

      if (toc) toc.hidden = themes === 0;

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

  // Contact form: submit in place, so nobody loses the page they were reading.
  // Without JS the form posts normally and kontakt.php redirects back.
  const contactForm = document.getElementById("contact-form");
  const contactStatus = document.getElementById("contact-status");
  if (contactForm && contactStatus) {
    const button = contactForm.querySelector(".contact__submit");

    const setStatus = (text, state) => {
      contactStatus.textContent = text;
      contactStatus.classList.remove("is-error", "is-success");
      if (state) contactStatus.classList.add(state);
    };

    contactForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!contactForm.reportValidity()) return;

      button.disabled = true;
      setStatus("Wird gesendet …", null);

      try {
        const response = await fetch(contactForm.action, {
          method: "POST",
          headers: { Accept: "application/json" },
          body: new FormData(contactForm),
        });
        const result = await response.json();
        if (result.ok) {
          contactForm.reset();
          setStatus(result.message || "Danke, ich melde mich!", "is-success");
        } else {
          setStatus(result.message || "Das hat nicht geklappt.", "is-error");
        }
      } catch (error) {
        setStatus("Das hat nicht geklappt. Bitte später noch einmal.", "is-error");
      } finally {
        button.disabled = false;
      }
    });

    // Rückweg ohne JavaScript: kontakt.php hängt das Ergebnis an die URL.
    const params = new URLSearchParams(window.location.search);
    if (params.has("gesendet")) setStatus("Danke, ich melde mich!", "is-success");
    if (params.has("fehler")) setStatus("Das hat nicht geklappt.", "is-error");
  }

  // Copyright year
  const yearEl = document.getElementById("copyright-year");
  if (yearEl) {
    yearEl.textContent = new Date().getFullYear();
  }

});
