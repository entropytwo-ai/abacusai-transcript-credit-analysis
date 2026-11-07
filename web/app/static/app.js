// Sortable tables, "Sync now" button and sync-status polling. No dependencies.
(function () {
  // Keep --hdr in sync with the sticky site header's real height so the dive-in
  // project headers lock flush beneath it (the header wraps on narrow screens).
  var siteHeader = document.querySelector("header.top");
  function setHdr() {
    if (siteHeader) document.documentElement.style.setProperty("--hdr", siteHeader.offsetHeight + "px");
  }
  setHdr();
  window.addEventListener("resize", setHdr);
  window.addEventListener("load", setHdr);

  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("thead th").forEach(function (th, col) {
      th.addEventListener("click", function () {
        var body = table.tBodies[0], rows = Array.prototype.slice.call(body.rows);
        var num = th.dataset.type === "num", asc = !th.classList.contains("asc");
        table.querySelectorAll("thead th").forEach(function (h) { h.classList.remove("asc", "desc"); });
        th.classList.add(asc ? "asc" : "desc");
        rows.sort(function (a, b) {
          var x = a.cells[col], y = b.cells[col];
          var vx = x.dataset.v !== undefined ? x.dataset.v : x.textContent.trim();
          var vy = y.dataset.v !== undefined ? y.dataset.v : y.textContent.trim();
          if (num) { vx = parseFloat(String(vx).replace(/[^0-9.\-]/g, "")) || 0; vy = parseFloat(String(vy).replace(/[^0-9.\-]/g, "")) || 0; }
          var r = num ? vx - vy : String(vx).localeCompare(String(vy), undefined, { sensitivity: "base" });
          return asc ? r : -r;
        });
        rows.forEach(function (r) { body.appendChild(r); });
      });
    });
  });

  var btn = document.getElementById("sync-now"), text = document.getElementById("sync-text");
  function poll() {
    fetch("/api/sync/status", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (s) {
      if (s.running) { if (text) text.textContent = "Sync running… (new chats, then excerpts)"; setTimeout(poll, 4000); }
      else { location.reload(); }
    }).catch(function () { setTimeout(poll, 8000); });
  }
  if (btn) {
    btn.addEventListener("click", function () {
      btn.disabled = true;
      var fd = new FormData(); fd.append("csrf", window.CSRF || "");
      fetch("/api/sync", { method: "POST", body: fd, credentials: "same-origin" }).then(function () { poll(); })
        .catch(function () { btn.disabled = false; });
    });
    if (btn.disabled) poll();
  }
})();
