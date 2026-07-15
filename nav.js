/* Forage Kitchen dashboards — shared navigation bar.
   Included by every dashboard via <script src="nav.js"></script> right after <body>.
   Self-contained: injects its own styles and markup, no dependencies. */
(function () {
  var LINKS = [
    { href: "index.html",                label: "Home",        match: ["index.html", ""] },
    { href: "daily_dashboard.html",      label: "Daily Sales", match: ["daily_dashboard.html"] },
    { href: "cogs_dashboard.html",       label: "COGS",        match: ["cogs_dashboard.html", "cogs_P"] },
    { href: "labor_dashboard.html",      label: "Labor",       match: ["labor_dashboard.html"] },
    { href: "dashboard.html",            label: "P&L",         match: ["dashboard.html"] },
    { href: "product_mix_analysis.html", label: "Product Mix", match: ["product_mix"] },
    { href: "seo_dashboard.html",        label: "SEO",         match: ["seo_dashboard.html"] },
    { href: "ads_dashboard.html",        label: "Paid Ads",    match: ["ads_dashboard.html"] },
    { href: "combined_dashboard.html",   label: "By Location", match: ["combined_dashboard.html"] }
  ];

  var page = window.location.pathname.split("/").pop();

  // Entries ending in ".html" (or "") match exactly; anything else is a
  // filename prefix (e.g. "cogs_P" covers the period archive pages).
  function isActive(link) {
    return link.match.some(function (m) {
      if (m === "" || m.slice(-5) === ".html") return page === m;
      return page.indexOf(m) === 0;
    });
  }

  var css = [
    ".forage-nav { background: #1e293b; border-bottom: 1px solid #334155; padding: 0 16px;",
    "  display: flex; align-items: center; gap: 4px; overflow-x: auto; white-space: nowrap;",
    "  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;",
    "  -webkit-overflow-scrolling: touch; scrollbar-width: none; }",
    ".forage-nav::-webkit-scrollbar { display: none; }",
    ".forage-nav .brand { color: #22c55e; font-weight: 700; font-size: 15px; padding: 12px 12px 12px 0;",
    "  text-decoration: none; flex-shrink: 0; }",
    ".forage-nav a.nav-link { color: #94a3b8; text-decoration: none; font-size: 13px; font-weight: 600;",
    "  padding: 12px 10px; border-bottom: 2px solid transparent; flex-shrink: 0; }",
    ".forage-nav a.nav-link:hover { color: #f8fafc; }",
    ".forage-nav a.nav-link.active { color: #f8fafc; border-bottom-color: #22c55e; }"
  ].join("\n");

  function build() {
    var style = document.createElement("style");
    style.textContent = css;
    document.head.appendChild(style);

    var nav = document.createElement("nav");
    nav.className = "forage-nav";

    var brand = document.createElement("a");
    brand.className = "brand";
    brand.href = "index.html";
    brand.textContent = "Forage";
    nav.appendChild(brand);

    LINKS.forEach(function (link) {
      var a = document.createElement("a");
      a.className = "nav-link" + (isActive(link) ? " active" : "");
      a.href = link.href;
      a.textContent = link.label;
      nav.appendChild(a);
    });

    document.body.insertBefore(nav, document.body.firstChild);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", build);
  } else {
    build();
  }
})();
