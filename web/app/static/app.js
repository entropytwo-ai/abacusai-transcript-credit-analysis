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

  // "A Word From Douglas Adams": play the video in an in-window modal instead of
  // leaving the page. Falls back to the plain link if JS is unavailable.
  var modal = document.getElementById("video-modal");
  if (modal) {
    var frame = modal.querySelector(".vmodal-frame");
    function openVideo(id) {
      frame.innerHTML = '<iframe src="https://www.youtube-nocookie.com/embed/' + id +
        '?autoplay=1&rel=0" title="A Word From Douglas Adams" frameborder="0" ' +
        'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" ' +
        'allowfullscreen></iframe>';
      modal.hidden = false;
      document.body.classList.add("vmodal-open");
    }
    function closeVideo() {
      modal.hidden = true;
      frame.innerHTML = "";
      document.body.classList.remove("vmodal-open");
    }
    document.querySelectorAll("a.adams-video").forEach(function (a) {
      a.addEventListener("click", function (e) {
        e.preventDefault();
        openVideo(a.dataset.video);
      });
    });
    modal.querySelectorAll("[data-close]").forEach(function (el) {
      el.addEventListener("click", closeVideo);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !modal.hidden) closeVideo();
    });
  }

  // "Show per-project delta": reveal the as-incurred / delta columns without
  // changing the default table width.
  var dtoggle = document.getElementById("delta-toggle");
  var stable = document.getElementById("summary");
  if (dtoggle && stable) {
    dtoggle.addEventListener("click", function (e) {
      e.preventDefault();
      var on = stable.classList.toggle("show-delta");
      dtoggle.textContent = on ? "Hide per-project delta" : "Show per-project delta";
    });
  }

  // "Active times per day": click a day column to zoom into that single day in a
  // modal with a tall, readable hour axis and the full list of turn times.
  var dayModal = document.getElementById("day-modal");
  var actchart = document.querySelector(".actchart");
  if (dayModal && actchart) {
    var cols = Array.prototype.slice.call(actchart.querySelectorAll(".daycol.clickable"));
    var plot = dayModal.querySelector(".daymodal-plot");
    var titleEl = dayModal.querySelector(".daymodal-title");
    var timesEl = dayModal.querySelector(".daymodal-times");
    var tz = dayModal.getAttribute("data-tz") || "";
    var cur = -1;

    function dotsOf(col) {
      return Array.prototype.slice.call(col.querySelectorAll(".dot")).map(function (s) {
        return { frac: parseFloat(s.getAttribute("data-frac")) || 0, label: s.getAttribute("data-label") || "" };
      }).sort(function (a, b) { return a.frac - b.frac; });
    }

    function renderDay(i) {
      cur = i;
      var col = cols[i];
      var day = col.getAttribute("data-day");
      var count = col.getAttribute("data-count");
      var dots = dotsOf(col);
      titleEl.textContent = day + " · " + count + " turn" + (count === "1" ? "" : "s") + (tz ? " (" + tz + ")" : "");

      var html = '<div class="dmp-axis">';
      for (var hr = 0; hr <= 24; hr += 2) {
        var top = ((24 - hr) / 24) * 100;
        html += '<i class="dmp-h" style="top:' + top + '%">' + (hr < 10 ? "0" + hr : hr) + ':00</i>';
        html += '<i class="dmp-gl" style="top:' + top + '%"></i>';
      }
      html += '</div><div class="dmp-dots">';
      var n = dots.length;
      for (var k = 0; k < n; k++) {
        var topd = (1 - dots[k].frac) * 100;
        var left = n > 1 ? (k / (n - 1)) * 100 : 50;
        html += '<span class="dmp-dot" style="top:' + topd + '%;left:' + left + '%" title="' + dots[k].label + '"></span>';
      }
      html += '</div>';
      plot.innerHTML = html;

      timesEl.innerHTML = dots.length
        ? '<span class="dmt-label">Times:</span> ' + dots.map(function (d) { return '<span class="dmt">' + d.label + '</span>'; }).join("")
        : "";

      dayModal.querySelector("[data-prev]").disabled = (i <= 0);
      dayModal.querySelector("[data-next]").disabled = (i >= cols.length - 1);
    }

    function openDay(i) {
      renderDay(i);
      dayModal.hidden = false;
      document.body.classList.add("vmodal-open");
    }
    function closeDay() {
      dayModal.hidden = true;
      document.body.classList.remove("vmodal-open");
    }

    cols.forEach(function (col, i) {
      col.addEventListener("click", function () { openDay(i); });
      col.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDay(i); }
      });
    });
    dayModal.querySelectorAll("[data-close]").forEach(function (el) { el.addEventListener("click", closeDay); });
    dayModal.querySelector("[data-prev]").addEventListener("click", function () { if (cur > 0) renderDay(cur - 1); });
    dayModal.querySelector("[data-next]").addEventListener("click", function () { if (cur < cols.length - 1) renderDay(cur + 1); });
    document.addEventListener("keydown", function (e) {
      if (dayModal.hidden) return;
      if (e.key === "Escape") closeDay();
      else if (e.key === "ArrowLeft" && cur > 0) renderDay(cur - 1);
      else if (e.key === "ArrowRight" && cur < cols.length - 1) renderDay(cur + 1);
    });
  }

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
