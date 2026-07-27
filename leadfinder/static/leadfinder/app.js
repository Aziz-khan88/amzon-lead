(function () {
  "use strict";

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function setupNavigation() {
    const toggle = document.querySelector(".nav-toggle");
    const nav = document.getElementById("primary-nav");
    if (!toggle || !nav) return;

    const closeNavigation = () => {
      nav.classList.remove("is-open");
      toggle.setAttribute("aria-expanded", "false");
    };

    toggle.addEventListener("click", () => {
      const open = nav.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
    });

    nav.addEventListener("click", (event) => {
      if (event.target.closest("a")) closeNavigation();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeNavigation();
    });
  }

  function setupPageReveal() {
    const items = Array.from(document.querySelectorAll(
      ".page-header, .dashboard-command, main > .panel, main > section, main > .two-column, .new-run-panel, .new-run-actions"
    )).slice(0, 24);

    if (reduceMotion || !("IntersectionObserver" in window)) {
      items.forEach((item) => item.classList.add("is-visible"));
      return;
    }

    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.04, rootMargin: "0px 0px -24px" });

    items.forEach((item, index) => {
      item.classList.add("ui-reveal");
      item.style.setProperty("--reveal-delay", `${Math.min(index, 6) * 45}ms`);
      observer.observe(item);
    });
  }

  function setupKeyboardSearch() {
    document.addEventListener("keydown", (event) => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "k") return;
      const search = document.querySelector("input[type='search'], #lookup-keyword, #id_keyword");
      if (!search) return;
      event.preventDefault();
      search.focus();
      if (typeof search.select === "function") search.select();
    });
  }

  function setupFormFeedback() {
    document.querySelectorAll("form").forEach((form) => {
      form.addEventListener("submit", () => {
        const submitter = form.querySelector("button[type='submit']");
        if (!submitter || submitter.classList.contains("no-loading-state")) return;
        submitter.classList.add("is-loading");
        submitter.setAttribute("aria-busy", "true");
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.body.classList.add("ui-ready");
    setupNavigation();
    setupPageReveal();
    setupKeyboardSearch();
    setupFormFeedback();
  });
})();
