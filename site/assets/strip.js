/* The model-vs-market strip: three lanes (model, Kalshi, Polymarket) on one 0-100 cent axis, with
   a zoom window below it. Everything is the home team's chance of winning, in cents.

   A strip input `s` looks like:
     { home: "Dallas", away: "Tampa Bay", awayCode: "TB",
       kalshi: {bid, ask} | undefined, poly: {bid, ask, flipped} | undefined,
       model: number | null, modelLabel: "Elo baseline (v0, untuned)", lockText: "..." }
   A quote with a null bid or ask is a one-sided or empty book and gets no bar. */
(function () {
  "use strict";
  var Lab = window.Lab;
  var esc = Lab.esc;

  var fmt = function (n) { return String(+n.toFixed(2)); };
  var fmt1 = function (n) { return String(+n.toFixed(1)); };
  var rng = function (r) { return fmt(r[0]) + "-" + fmt(r[1]) + "¢"; };
  var mid = function (r) { return (r[0] + r[1]) / 2; };

  function range(q) { return q && q.bid != null && q.ask != null ? [q.bid, q.ask] : null; }
  function why(q) { return q ? "One-sided or empty book" : "No quote in this snapshot"; }

  /* Zoom window: about 20 cents wide, centered on the data, snapped to 5. */
  function windowFor(s) {
    var vals = [];
    [range(s.kalshi), range(s.poly)].forEach(function (r) { if (r) vals.push(r[0], r[1]); });
    if (s.model != null) vals.push(s.model);
    if (!vals.length) return [30, 70];
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    var width = Math.max(20, Math.ceil((hi - lo + 8) / 5) * 5);
    var start = Math.round(((lo + hi) / 2 - width / 2) / 5) * 5;
    start = Math.max(0, Math.min(100 - width, start));
    return [start, start + width];
  }

  function ruler(win, full) {
    var span = win[1] - win[0];
    var P = function (v) { return ((v - win[0]) / span * 100).toFixed(3); };
    var step = full ? 25 : span <= 25 ? 5 : span <= 50 ? 10 : 25, ticks = "", grid = "";
    for (var v = win[0]; v <= win[1] + 0.001; v += step) {
      ticks += '<span class="tick" style="left:' + P(v) + '%"><i></i><b>' + v + "¢</b></span>";
      if (v > win[0] && v < win[1]) grid += '<i class="gl" style="left:' + P(v) + '%"></i>';
    }
    return { ticks: ticks, grid: grid, P: P };
  }

  function plot(s, win, o) {
    var span = win[1] - win[0];
    var R = ruler(win, o.full), P = R.P, h = "";
    var model = s.model, kr = range(s.kalshi);
    // model lane (the zoom drops the empty slot; it only shows the model once it exists)
    if (model == null && !o.full) {
      // nothing: the full strip above already says when the model locks
    } else if (model == null) {
      h += '<div class="lane empty k-model"><div class="lab"><span class="nm">' + esc(s.modelLabel) + "</span></div>" +
           '<div class="slot">' + esc(s.lockText) + "</div></div>";
    } else {
      h += '<div class="lane k-model"><div class="lab" data-x="' + P(model) + '"><span class="nm">' +
           esc(o.full ? s.modelLabel : s.modelShort) + "</span>" +
           (o.full ? '<span class="v num">' + fmt(model) + "¢</span>" : "") + "</div>" +
           '<div class="trk"><span class="rail"></span>';
      if (kr) {
        var km = mid(kr), a = Math.min(model, km), b = Math.max(model, km);
        h += '<span class="gapline" style="left:' + P(a) + "%;width:" + (P(b) - P(a)).toFixed(3) + '%"></span>';
      }
      h += '<span class="dia" style="left:' + P(model) + '%"></span></div></div>';
    }
    // market lanes
    [["kalshi", "Kalshi", s.kalshi], ["poly", "Polymarket", s.poly]].forEach(function (m) {
      var r = range(m[2]);
      if (!r) {
        if (!o.full) return;
        h += '<div class="lane empty k-' + m[0] + '"><div class="lab"><span class="nm">' + m[1] + "</span></div>" +
             '<div class="slot quiet">' + why(m[2]) + "</div></div>";
        return;
      }
      h += '<div class="lane k-' + m[0] + '"><div class="lab" data-x="' + P(mid(r)) + '"><span class="nm">' + m[1] + "</span>" +
           (o.full ? '<span class="v num">' + rng(r) + "</span>" : "") + "</div>" +
           '<div class="trk"><span class="rail"></span><span class="bar" style="left:' + P(mid(r)) + "%;--w:" +
           ((r[1] - r[0]) * 100 / span).toFixed(3) + '">' + "<i></i></span></div></div>";
    });
    var extra = "";
    if (model != null) extra += '<i class="guide" style="left:' + P(model) + '%"></i>';
    if (o.full && o.zoom) extra += '<i class="win" style="left:' + P(o.zoom[0]) + "%;width:" + (P(o.zoom[1]) - P(o.zoom[0])).toFixed(3) + '%"></i>';
    var title = o.full ? "Probability " + esc(s.home) + " wins (0–100¢)" : "Zoomed: " + win[0] + "–" + win[1] + "¢";
    return '<div class="plot' + (o.full ? "" : " zoomed") + '"><div class="lanes">' + R.grid + extra + h + "</div>" +
           '<div class="ruler">' + R.ticks + '</div><p class="ax-title">' + title + "</p></div>";
  }

  function aria(s) {
    var kr = range(s.kalshi), pr = range(s.poly);
    var t = "Probability " + s.home + " wins, in cents. ";
    t += kr ? "Kalshi bid " + fmt(kr[0]) + " to ask " + fmt(kr[1]) + ". " : "Kalshi: " + why(s.kalshi).toLowerCase() + ". ";
    t += pr ? "Polymarket bid " + fmt(pr[0]) + " to ask " + fmt(pr[1]) + ". " : "Polymarket: " + why(s.poly).toLowerCase() + ". ";
    if (s.model == null) return t + s.modelLabel + " is not logged yet. " + s.lockText;
    t += s.modelLabel + " " + fmt(s.model);
    if (!kr) return t + ".";
    var g = s.model - mid(kr);
    return t + ", " + (Math.abs(g) < 1 ? "within 1 cent of" : Math.abs(g).toFixed(1) + " cents " + (g > 0 ? "above" : "below")) +
           " the Kalshi mid of " + fmt1(mid(kr)) + ".";
  }

  function gap(s) {
    var kr = range(s.kalshi);
    if (s.model == null || !kr) return "";
    var g = s.model - mid(kr), mag = Math.abs(g).toFixed(1);
    var txt = Math.abs(g) < 1 ? "Model is within 1¢ of the Kalshi mid" : "Model is " + (g > 0 ? "above" : "below") + " the Kalshi mid";
    var inside = s.model >= kr[0] && s.model <= kr[1] ? ", inside its bid-ask" : "";
    return '<div class="gapread"><span class="gv num">' + (g > 0 ? "+" : "−") + mag + "¢</span><span>" + txt +
           " (" + fmt1(mid(kr)) + "¢) now" + inside + "</span></div>";
  }

  /* Each label sits above its own lane, ending at its marker and clamped inside the plot. */
  function place(root) {
    root.querySelectorAll(".lanes").forEach(function (lanes) {
      var W = lanes.clientWidth;
      lanes.querySelectorAll(".lab[data-x]").forEach(function (lab) {
        var w = lab.offsetWidth, x = parseFloat(lab.dataset.x) / 100 * W;
        lab.style.left = Math.max(0, Math.min(W - w, x - w + 8)) + "px";
      });
      lanes.querySelectorAll(".bar").forEach(function (b) { b.classList.toggle("wide", b.offsetWidth >= 14); });
    });
  }

  function build(el, s) {
    s.modelShort = s.modelShort || "Elo baseline";
    var win = windowFor(s);
    el.innerHTML = '<div role="img" aria-label="' + esc(aria(s)) + '">' +
                   plot(s, [0, 100], { full: true, zoom: win }) + plot(s, win, { full: false }) + "</div>";
    place(el);
  }

  /* One compact row for the week list: model, Kalshi and Polymarket lanes on a shared 0-100 axis. */
  function mini(s) {
    var P = function (v) { return v.toFixed(3); };
    var h = '<div class="mini" role="img" aria-label="' + esc(aria(s)) + '">';
    [25, 50, 75].forEach(function (v) { h += '<i class="gl" style="left:' + v + '%"></i>'; });
    // No model lane until a forecast exists: the row's status text already says when it locks.
    if (s.model != null) {
      h += '<i class="guide" style="left:' + P(s.model) + '%"></i>' +
           '<div class="ml"><span class="rail"></span><span class="dia" style="left:' + P(s.model) + '%"></span></div>';
    }
    [s.kalshi, s.poly].forEach(function (q) {
      var r = range(q);
      h += '<div class="ml' + (r ? "" : " none") + '">' + (r
        ? '<span class="rail"></span><span class="bar" style="left:' + P(mid(r)) + "%;--w:" + (r[1] - r[0]).toFixed(3) + '"></span>'
        : "<span>" + why(q) + "</span>") + "</div>";
    });
    return h + "</div>";
  }

  function ticks100() {
    var R = ruler([0, 100], true);
    return '<div class="ruler">' + R.ticks + "</div>";
  }

  /* The cross-venue note, from market.json's `cross` object (built in jobs/build_site.py). */
  var signed = function (n) { return (n > 0 ? "+" : n < 0 ? "−" : "") + fmt1(Math.abs(n)); };
  Lab.crossNote = function (c, s) {
    if (!c) return "";
    var name = function (v) { return v === "kalshi" ? "Kalshi" : "Polymarket"; };
    var t = "<b>Cross-venue gap</b> " + fmt(c.gross) + "¢ gross: buy " + esc(s.home) + " on " + name(c.buy) + " at " + fmt(c.buy_price) +
      "¢, sell it on " + name(c.sell) + " at " + fmt(c.sell_price) + "¢. ";
    if (c.net == null) t += "Kalshi fee data was unavailable, so there is no net figure. ";
    else if (!c.survives) t += "After est. fees (Kalshi " + fmt1(c.kalshi_fee) + "¢): " + signed(c.net) + "¢, so it doesn't survive. ";
    else t += "After est. fees (Kalshi " + fmt1(c.kalshi_fee) + "¢): " + signed(c.net) + "¢. Polymarket US's fee isn't counted. ";
    return t + "Paper only; order size not checked.";
  };

  Lab.strip = { build: build, place: place, gap: gap, mini: mini, ticks100: ticks100, range: range, mid: mid, fmt: fmt, fmt1: fmt1, rng: rng };

  /* Shared by the home and week pages: what the model lane says before there is a model. */
  Lab.MODEL_LABELS = { "elo-538-default-v0": "Elo baseline (v0, untuned)" };
  /* Where a game stands, from the data and the viewer's clock (not the build time):
       logged  a forecast CSV is on main
       locks   lock time is still ahead
       missed  lock time has passed and no forecast was logged: "Not logged" */
  Lab.lockState = function (g, now) {
    if (g.logged) return "logged";
    return new Date(g.lock_utc) > now ? "locks" : "missed";
  };
  Lab.lockText = function (g, now) {
    var st = Lab.lockState(g, now);
    if (st === "locks") return "Model locks " + Lab.stamp(new Date(g.lock_utc)) + " (24h before kickoff)";
    if (new Date(g.kickoff_utc) > now) return "Not logged. It shows here once the forecast is pushed to GitHub.";
    return "Not logged. No forecast was made before kickoff.";
  };
  Lab.stripInput = function (g, market, now) {
    var q = (market.games || {})[g.id] || {};
    var m = g.model;
    return {
      home: Lab.team(g.home), away: Lab.team(g.away), awayCode: g.away,
      kalshi: q.kalshi, poly: q.polymarket_us,
      model: m ? m.p_home : null,
      modelLabel: m ? (Lab.MODEL_LABELS[m.name] || m.name) : "Elo baseline (v0, untuned)",
      modelShort: "Elo baseline",
      lockText: Lab.lockText(g, now)
    };
  };
})();
