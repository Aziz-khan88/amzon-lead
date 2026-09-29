/* ==========================================================================
   UX Polish Layer — interactivity
   Counters, staggered reveals, ripples, toasts, copy buttons, animated
   gauges, back-to-top. Same theme; degrades gracefully with reduced motion.
   ========================================================================== */
(function () {
  "use strict";

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ── 1. Staggered entrances for card grids ─────────────────────────────── */
  function setupStagger() {
    if (reduceMotion) return;
    const grids = document.querySelectorAll([
      ".modern-kpi-grid",
      ".role-kpi-grid",
      ".metric-grid",
      ".dashboard-main-grid",
      ".tool-grid",
      ".flow-grid",
      ".quick-action-list",
      ".recent-run-list",
      ".batch-list",
      ".team-performance-grid",
      ".sales-dashboard-grid",
      ".category-groups",
      ".command-list",
      ".error-chip-list",
      ".lead-stat-grid",
      ".run-stat-grid"
    ].join(","));

    grids.forEach((grid) => {
      grid.classList.add("ux-stagger");
      Array.from(grid.children).forEach((child, i) => {
        child.style.setProperty("--ux-i", Math.min(i, 10));
      });
    });

    // Table rows cascade in (cap so big tables stay snappy)
    document.querySelectorAll(".table tbody").forEach((tbody) => {
      Array.from(tbody.rows).slice(0, 30).forEach((row, i) => {
        row.style.setProperty("--ux-row", i);
      });
    });
  }

  /* ── 2. Animated number counters ───────────────────────────────────────── */
  function animateCounter(el) {
    const raw = el.textContent.trim();
    const match = raw.match(/^(-?[\d,]+)(%?)$/);
    if (!match) return;
    const target = parseInt(match[1].replace(/,/g, ""), 10);
    if (isNaN(target) || target === 0) return;
    const suffix = match[2];

    if (reduceMotion) return;

    const duration = 850;
    const start = performance.now();
    function tick(now) {
      const p = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic
      el.textContent = Math.round(target * eased).toLocaleString() + suffix;
      if (p < 1) {
        requestAnimationFrame(tick);
      } else {
        el.textContent = target.toLocaleString() + suffix;
        el.classList.add("ux-counted");
      }
    }
    el.textContent = "0" + suffix;
    requestAnimationFrame(tick);
  }

  function setupCounters() {
    const targets = document.querySelectorAll([
      ".modern-kpi-card strong",
      ".role-kpi-grid a strong",
      ".metric strong",
      ".lead-stat-card strong",
      ".run-stat-card strong",
      ".coverage-gauge > div strong",
      ".verification-donut > div strong",
      ".team-performance-grid article p strong",
      ".analytics-footer strong"
    ].join(","));

    if (!("IntersectionObserver" in window)) {
      targets.forEach(animateCounter);
      return;
    }
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        io.unobserve(entry.target);
        animateCounter(entry.target);
      });
    }, { threshold: 0.4 });
    targets.forEach((t) => io.observe(t));
  }

  /* ── 3. Animated donut & coverage gauge ────────────────────────────────── */
  function animateGauge(el, apply, duration) {
    if (reduceMotion) return;
    const start = performance.now();
    function tick(now) {
      const p = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      apply(eased);
      if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }

  function setupGauges() {
    // Verification donut: --verified / --other percentages
    document.querySelectorAll(".verification-donut").forEach((donut) => {
      const verified = parseFloat(donut.style.getPropertyValue("--verified")) || 0;
      const other = parseFloat(donut.style.getPropertyValue("--other")) || 0;
      if (!verified && !other) return;
      animateGauge(donut, (e) => {
        donut.style.setProperty("--verified", (verified * e).toFixed(2) + "%");
        donut.style.setProperty("--other", (other * e).toFixed(2) + "%");
      }, 950);
    });

    // Coverage gauge: animate --coverage-angle from 0 to target
    document.querySelectorAll(".coverage-gauge").forEach((gauge) => {
      const label = gauge.querySelector("strong");
      const percent = label ? parseFloat(label.textContent) : NaN;
      if (isNaN(percent)) return;
      const target = percent * 3.6;
      gauge.style.setProperty("--coverage-angle", "0deg");
      animateGauge(gauge, (e) => {
        gauge.style.setProperty("--coverage-angle", (target * e).toFixed(1) + "deg");
      }, 950);
    });
  }

  /* ── 4. Button ripple ──────────────────────────────────────────────────── */
  function setupRipples() {
    if (reduceMotion) return;
    document.addEventListener("pointerdown", (event) => {
      const btn = event.target.closest(".btn");
      if (!btn || btn.disabled) return;
      const rect = btn.getBoundingClientRect();
      const size = Math.max(rect.width, rect.height);
      const ripple = document.createElement("span");
      ripple.className = "ux-ripple";
      ripple.style.width = ripple.style.height = size + "px";
      ripple.style.left = event.clientX - rect.left - size / 2 + "px";
      ripple.style.top = event.clientY - rect.top - size / 2 + "px";
      btn.appendChild(ripple);
      ripple.addEventListener("animationend", () => ripple.remove());
    });
  }

  /* ── 5. Toast stack: alerts become dismissible floating toasts ─────────── */
  function ensureToastStack() {
    let stack = document.querySelector(".ux-toast-stack");
    if (!stack) {
      stack = document.createElement("div");
      stack.className = "ux-toast-stack";
      stack.setAttribute("aria-live", "polite");
      document.body.appendChild(stack);
    }
    return stack;
  }

  function dismissToast(el) {
    if (el.classList.contains("ux-leaving")) return;
    el.classList.add("ux-leaving");
    el.addEventListener("animationend", () => el.remove(), { once: true });
  }

  function decorateToast(el, timeout) {
    const close = document.createElement("button");
    close.type = "button";
    close.className = "ux-toast-close";
    close.setAttribute("aria-label", "Dismiss notification");
    close.innerHTML = "&times;";
    close.addEventListener("click", () => dismissToast(el));
    el.appendChild(close);

    if (!reduceMotion && timeout > 0) {
      const bar = document.createElement("span");
      bar.className = "ux-toast-progress";
      bar.style.animationDuration = timeout + "ms";
      el.appendChild(bar);
      const timer = setTimeout(() => dismissToast(el), timeout);
      el.addEventListener("pointerenter", () => clearTimeout(timer), { once: true });
    }
  }

  function setupAlerts() {
    const alerts = document.querySelectorAll(".app-content > .alert");
    if (!alerts.length) return;
    const stack = ensureToastStack();
    alerts.forEach((alert) => {
      stack.appendChild(alert);
      const isError = alert.classList.contains("alert-danger");
      decorateToast(alert, isError ? 9000 : 5500);
    });
  }

  /* Global helper so future code can raise toasts */
  window.uxToast = function (message, kind) {
    const stack = ensureToastStack();
    const el = document.createElement("div");
    el.className = "alert alert-" + (kind || "success") + " ux-toast d-flex align-items-center gap-2";
    el.textContent = message;
    stack.appendChild(el);
    decorateToast(el, 3000);
  };

  /* ── 6. Copy-to-clipboard on contact links ─────────────────────────────── */
  function setupCopyButtons() {
    document.querySelectorAll('a[href^="mailto:"]').forEach((link) => {
      if (link.dataset.uxCopyReady) return;
      link.dataset.uxCopyReady = "1";
      const address = link.href.replace(/^mailto:/i, "").split("?")[0];
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ux-copy-btn";
      btn.textContent = "Copy";
      btn.setAttribute("aria-label", "Copy email address " + address);
      btn.addEventListener("click", (event) => {
        event.preventDefault();
        const done = () => {
          btn.textContent = "Copied ✓";
          btn.classList.add("ux-copied");
          window.uxToast("Email copied to clipboard", "success");
          setTimeout(() => {
            btn.textContent = "Copy";
            btn.classList.remove("ux-copied");
          }, 1800);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(address).then(done).catch(() => {});
        } else {
          const tmp = document.createElement("textarea");
          tmp.value = address;
          document.body.appendChild(tmp);
          tmp.select();
          try { document.execCommand("copy"); done(); } catch (e) { /* noop */ }
          tmp.remove();
        }
      });
      link.insertAdjacentElement("afterend", btn);
    });
  }

  /* ── 7. Back-to-top ────────────────────────────────────────────────────── */
  function setupBackToTop() {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "ux-backtop";
    btn.setAttribute("aria-label", "Back to top");
    btn.innerHTML = '<i class="ph-bold ph-arrow-up"></i>';
    document.body.appendChild(btn);

    let ticking = false;
    const handleScroll = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        const scrolled = window.scrollY || document.documentElement.scrollTop || (document.body ? document.body.scrollTop : 0);
        btn.classList.toggle("ux-show", scrolled > 260);
        ticking = false;
      });
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    document.addEventListener("scroll", handleScroll, { passive: true });

    btn.addEventListener("click", () => {
      const behavior = reduceMotion ? "auto" : "smooth";
      try { window.scrollTo({ top: 0, behavior }); } catch (e) { window.scrollTo(0, 0); }
      try { document.documentElement.scrollTo({ top: 0, behavior }); } catch (e) { document.documentElement.scrollTop = 0; }
      if (document.body) {
        try { document.body.scrollTo({ top: 0, behavior }); } catch (e) { document.body.scrollTop = 0; }
      }
    });
  }

  /* ── 8. Helpful tooltips on icon-only controls ─────────────────────────── */
  function setupTooltips() {
    document.querySelectorAll("[title]").forEach((el) => {
      if (el.tagName === "ABBR" || el.closest("table") || el.classList.contains("ux-backtop")) return;
      const title = el.getAttribute("title");
      if (!title || el.dataset.tip) return;
      el.setAttribute("data-tip", title);
      el.removeAttribute("title"); // avoid double native tooltip
    });
  }

  /* ── 9. Table Dropdown Elevation ───────────────────────────────────────── */
  function setupDropdownElevation() {
    document.addEventListener("show.bs.dropdown", (e) => {
      const row = e.target.closest("tr");
      if (row) {
        row.classList.add("has-open-dropdown");
        const td = e.target.closest("td");
        if (td) td.classList.add("has-open-dropdown");
      }
    });

    document.addEventListener("hidden.bs.dropdown", (e) => {
      const row = e.target.closest("tr");
      if (row) {
        row.classList.remove("has-open-dropdown");
        const td = e.target.closest("td");
        if (td) td.classList.remove("has-open-dropdown");
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    setupStagger();
    setupCounters();
    setupGauges();
    setupRipples();
    setupAlerts();
    setupCopyButtons();
    setupBackToTop();
    setupTooltips();
    setupDropdownElevation();
  });
})();

