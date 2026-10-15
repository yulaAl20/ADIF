// Interactive explanations on the home and how-it-works pages. Plain JS, no dependencies.
(function () {
  "use strict";
  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var SVGNS = "http://www.w3.org/2000/svg";
  var DYES = { "ocean blue": "#1F6E9C", "coconut white": "#F3EFE4", "cinnamon": "#A8592A" };

  function press(group, button) {
    group.forEach(function (b) { b.setAttribute("aria-pressed", b === button ? "true" : "false"); });
  }
  function pressed(group) {
    for (var i = 0; i < group.length; i++) if (group[i].getAttribute("aria-pressed") === "true") return group[i];
    return group[0];
  }

  // ------------------------------------------------------------ ADID banner
  var show = document.querySelector("[data-showcase]");
  var dataEl = document.getElementById("showcase-data");
  if (show && dataEl) {
    var variants = JSON.parse(dataEl.textContent);
    var swatches = Array.prototype.slice.call(show.querySelectorAll("[data-colour]"));
    var chips = Array.prototype.slice.call(show.querySelectorAll("[data-size]"));
    var itemBtn = show.querySelector("[data-item]");
    var itemIndex = -1;

    var el = function (sel) { return show.querySelector(sel); };
    var drawQr = function (qr) {
      var g = el("[data-qr]");
      while (g.firstChild) g.removeChild(g.firstChild);
      if (!qr || !qr.size) return;
      var path = document.createElementNS(SVGNS, "path");
      path.setAttribute("d", qr.d);
      path.setAttribute("fill", "#1D1F24");
      path.setAttribute("transform", "scale(" + (112 / qr.size) + ")");
      g.appendChild(path);
    };

    var update = function (animate) {
      var colour = pressed(swatches).getAttribute("data-colour");
      var size = pressed(chips).getAttribute("data-size");
      var v = variants.filter(function (x) { return x.colour === colour && x.size === size; })[0] || variants[0];
      var hasItems = v.items && v.items.length;
      if (!hasItems) itemIndex = -1;
      itemBtn.disabled = !hasItems;
      itemBtn.setAttribute("aria-pressed", itemIndex >= 0 ? "true" : "false");
      itemBtn.textContent = itemIndex >= 0 ? "Next serialised shirt" : "Pick a serialised shirt";
      var item = itemIndex >= 0 ? v.items[itemIndex] : null;
      el("[data-item-note]").textContent = hasItems
        ? (item ? "Serial " + item.serial + " (" + (itemIndex + 1) + " of " + v.items.length + ")" : v.items.length + " shirts of this variant are serialised")
        : "Try Ocean Blue, size M: three of those shirts are serialised";

      var varEl = el("[data-a-var]"), itemEl = el("[data-a-item]");
      varEl.textContent = "/" + v.segment;
      itemEl.textContent = item ? "/" + item.uuid : "";
      el("[data-k-var]").textContent = "/" + v.segment + " is " + v.colour + ", size " + v.size + ". GTIN " + v.gtin + " opens it too.";
      el("[data-k-item]").textContent = item ? "Serial " + item.serial + ". Opens by scan only; never listed publicly." : "Only serialised garments have this part.";
      if (animate && !reduced) {
        [varEl, itemEl].forEach(function (n) { n.classList.remove("flash-in"); void n.offsetWidth; n.classList.add("flash-in"); });
      }
      var tee = el("[data-tee]");
      tee.setAttribute("fill", DYES[colour.toLowerCase()] || "#888");
      el("[data-tag-line]").textContent = colour + ", size " + size + (item ? ", serial " + item.serial : "");
      el("[data-tag-gtin]").textContent = "GTIN " + v.gtin;
      drawQr(item ? item.qr : v.qr);
      el("[data-open]").setAttribute("href", item ? item.path : v.path);
    };

    swatches.forEach(function (b) { b.addEventListener("click", function () { press(swatches, b); itemIndex = -1; update(true); }); });
    chips.forEach(function (b) { b.addEventListener("click", function () { press(chips, b); itemIndex = -1; update(true); }); });
    itemBtn.addEventListener("click", function () {
      var colour = pressed(swatches).getAttribute("data-colour"), size = pressed(chips).getAttribute("data-size");
      var v = variants.filter(function (x) { return x.colour === colour && x.size === size; })[0];
      if (!v || !v.items.length) return;
      itemIndex = (itemIndex + 1) % v.items.length;
      update(true);
    });
    update(false);
  }

  // ------------------------------------------------------- connection map
  var related = document.querySelector("[data-related]");
  if (related) {
    var tabs = Array.prototype.slice.call(related.querySelectorAll("[data-rel]"));
    var svg = related.querySelector(".rel-map svg");
    var caption = related.querySelector("[data-rel-caption]");
    var captions = {
      design: "Up to the design, down to three serialised shirts.",
      siblings: "Sideways to the other colours and sizes of the same design.",
      lot: "Ocean Blue S and L came from the same batch. Private to the maker and authorities.",
      similar: "Blue T-shirts from other designs and makers, however they spelt “blue”."
    };
    var timer = null;
    var select = function (key) {
      tabs.forEach(function (t) { t.setAttribute("aria-selected", t.getAttribute("data-rel") === key ? "true" : "false"); });
      svg.setAttribute("data-active", key);
      svg.querySelectorAll("[data-g]").forEach(function (n) {
        var on = (" " + n.getAttribute("data-g") + " ").indexOf(" " + key + " ") >= 0;
        n.classList.toggle("on", on);
      });
      caption.textContent = captions[key];
    };
    var stop = function () { if (timer) { clearInterval(timer); timer = null; } };
    tabs.forEach(function (t) {
      t.addEventListener("click", function () { stop(); select(t.getAttribute("data-rel")); });
      t.addEventListener("keydown", function (e) {
        var i = tabs.indexOf(t);
        if (e.key === "ArrowDown" || e.key === "ArrowRight") { e.preventDefault(); tabs[(i + 1) % tabs.length].focus(); tabs[(i + 1) % tabs.length].click(); }
        if (e.key === "ArrowUp" || e.key === "ArrowLeft") { e.preventDefault(); tabs[(i + tabs.length - 1) % tabs.length].focus(); tabs[(i + tabs.length - 1) % tabs.length].click(); }
      });
    });
    select("design");
    if (!reduced && "IntersectionObserver" in window) {
      var n = 0;
      new IntersectionObserver(function (entries, obs) {
        if (!entries[0].isIntersecting) return;
        obs.disconnect();
        timer = setInterval(function () {
          n = (n + 1) % tabs.length;
          select(tabs[n].getAttribute("data-rel"));
          if (n === 0) stop();
        }, 3200);
      }, { threshold: 0.5 }).observe(related);
    }
  }

  // --------------------------------------------------- role journeys (how)
  var journeys = document.querySelector("[data-journeys]");
  if (journeys) {
    var roles = Array.prototype.slice.call(journeys.querySelectorAll("[data-role]"));
    var panels = Array.prototype.slice.call(journeys.querySelectorAll("[data-journey]"));
    var playTimer = null;

    var buildFlow = function (panel) {
      if (panel._built) return panel._built;
      var steps = Array.prototype.slice.call(panel.querySelectorAll(".j-steps li"));
      var holder = panel.querySelector(".j-flow");
      var n = steps.length, w = 640, h = 150, pad = 46;
      var gap = (w - pad * 2) / (n - 1);
      var s = document.createElementNS(SVGNS, "svg");
      s.setAttribute("viewBox", "0 0 " + w + " " + h);
      s.setAttribute("aria-hidden", "true");
      var track = document.createElementNS(SVGNS, "line");
      track.setAttribute("x1", pad); track.setAttribute("x2", w - pad);
      track.setAttribute("y1", 64); track.setAttribute("y2", 64);
      track.setAttribute("class", "j-track");
      s.appendChild(track);
      var fill = track.cloneNode();
      fill.setAttribute("class", "j-fill");
      fill.setAttribute("x2", pad);
      s.appendChild(fill);
      var dots = [];
      steps.forEach(function (li, i) {
        var g = document.createElementNS(SVGNS, "g");
        g.setAttribute("class", "j-node");
        g.setAttribute("transform", "translate(" + (pad + i * gap) + " 64)");
        var c = document.createElementNS(SVGNS, "circle");
        c.setAttribute("r", 24);
        g.appendChild(c);
        var icon = document.createElementNS(SVGNS, "path");
        icon.setAttribute("d", li.getAttribute("data-icon") || "M-6 0h12");
        icon.setAttribute("class", "j-icon");
        g.appendChild(icon);
        var t = document.createElementNS(SVGNS, "text");
        t.setAttribute("y", 52);
        t.setAttribute("text-anchor", "middle");
        t.textContent = li.getAttribute("data-short") || String(i + 1);
        g.appendChild(t);
        g.style.cursor = "pointer";
        g.addEventListener("click", function () { stopPlay(); go(panel, i); });
        s.appendChild(g);
        dots.push(g);
        li.addEventListener("click", function () { stopPlay(); go(panel, i); });
      });
      var pulse = document.createElementNS(SVGNS, "circle");
      pulse.setAttribute("r", 28);
      pulse.setAttribute("class", "j-pulse");
      pulse.setAttribute("cy", 64);
      pulse.setAttribute("cx", pad);
      s.appendChild(pulse);
      holder.appendChild(s);
      panel._built = { steps: steps, dots: dots, fill: fill, pulse: pulse, pad: pad, gap: gap, at: 0 };
      return panel._built;
    };

    var go = function (panel, i) {
      var f = buildFlow(panel);
      f.at = i;
      var x = f.pad + i * f.gap;
      f.fill.setAttribute("x2", x);
      f.pulse.setAttribute("cx", x);
      f.dots.forEach(function (d, k) { d.classList.toggle("done", k < i); d.classList.toggle("now", k === i); });
      f.steps.forEach(function (li, k) { li.classList.toggle("now", k === i); li.classList.toggle("done", k < i); });
    };

    var stopPlay = function () {
      if (playTimer) { clearInterval(playTimer); playTimer = null; }
      journeys.querySelectorAll("[data-play]").forEach(function (b) { b.textContent = "Play the journey"; });
    };
    var play = function (panel) {
      stopPlay();
      var f = buildFlow(panel);
      go(panel, 0);
      panel.querySelector("[data-play]").textContent = "Pause";
      playTimer = setInterval(function () {
        if (f.at >= f.steps.length - 1) { stopPlay(); return; }
        go(panel, f.at + 1);
      }, 2400);
    };

    var choose = function (key, autoplay) {
      roles.forEach(function (r) { r.setAttribute("aria-selected", r.getAttribute("data-role") === key ? "true" : "false"); });
      panels.forEach(function (p) {
        var on = p.getAttribute("data-journey") === key;
        p.hidden = !on;
        if (on) { buildFlow(p); go(p, 0); if (autoplay && !reduced) play(p); }
      });
      try { history.replaceState(null, "", "#as-" + key); } catch (e) { /* ignore */ }
    };

    roles.forEach(function (r) {
      r.addEventListener("click", function () { choose(r.getAttribute("data-role"), true); });
    });
    panels.forEach(function (p) {
      var btn = p.querySelector("[data-play]");
      if (btn) btn.addEventListener("click", function () { if (playTimer) stopPlay(); else play(p); });
    });
    var initial = (location.hash || "").replace("#as-", "");
    var known = roles.map(function (r) { return r.getAttribute("data-role"); });
    choose(known.indexOf(initial) >= 0 ? initial : known[0], false);
  }

  // -------------------------------------------------- data journey (how)
  var pipe = document.querySelector("[data-pipeline]");
  if (pipe) {
    var cols = Array.prototype.slice.call(pipe.querySelectorAll("[data-col]"));
    var bins = {};
    pipe.querySelectorAll("[data-bin]").forEach(function (b) { bins[b.getAttribute("data-bin")] = b.querySelector(".bin-items"); });
    var runBtn = pipe.querySelector("[data-run]");
    var running = false;
    var reset = function () {
      Object.keys(bins).forEach(function (k) { bins[k].innerHTML = ""; });
      cols.forEach(function (c) { c.classList.remove("sent", "active"); });
    };
    var run = function () {
      if (running) return;
      running = true;
      runBtn.disabled = true;
      reset();
      var i = 0;
      var step = function () {
        if (i > 0) cols[i - 1].classList.remove("active");
        if (i >= cols.length) { cols[cols.length - 1].classList.remove("active"); running = false; runBtn.disabled = false; runBtn.textContent = "Run it again"; return; }
        var c = cols[i];
        c.classList.add("active");
        var to = c.getAttribute("data-to");
        setTimeout(function () {
          var chip = document.createElement("li");
          chip.className = "bin-chip" + (reduced ? "" : " drop");
          chip.innerHTML = "<span>" + c.getAttribute("data-field") + "</span><small>" + c.getAttribute("data-col") + "</small>";
          bins[to].appendChild(chip);
          c.classList.add("sent");
          i++;
          setTimeout(step, reduced ? 0 : 420);
        }, reduced ? 0 : 520);
      };
      step();
    };
    runBtn.addEventListener("click", run);
    if (!reduced && "IntersectionObserver" in window) {
      new IntersectionObserver(function (entries, obs) {
        if (entries[0].isIntersecting) { obs.disconnect(); run(); }
      }, { threshold: 0.4 }).observe(pipe);
    } else {
      run();
    }
  }
})();
