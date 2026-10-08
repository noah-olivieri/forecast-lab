/* The model-vs-market strip: label | plot | value lanes on one 0-100 cent axis, with a zoom
   block below it. Everything is the home team's chance of winning, in cents.

   A strip input `s` (see Lab.stripInput) has: home, away, kalshi/poly ({bid, ask, ...} or
   undefined), model (cents or null), modelLabel, cross. A quote with a null bid or ask is a
   one-sided or empty book and gets no bar. The model value is only ever games.json's `model`,
   which build_site.py fills from a forecast CSV that is on main and was created before kickoff. */
(function () {
  "use strict";
  var Lab = window.Lab, esc = Lab.esc, fmt = Lab.fmt, fmt1 = Lab.fmt1, range = Lab.range, mid = Lab.mid, signed = Lab.signed;

  Lab.MODEL_LABELS = { "elo-538-default-v0": "Elo baseline (v0, untuned)" };
  Lab.stripInput = function (g, market, now) {
    var q = (market.games || {})[g.id] || {}, m = g.model;
    return {
      id: g.id, home: Lab.team(g.home), away: Lab.team(g.away),
      kalshi: q.kalshi, poly: q.polymarket_us, cross: q.cross,
      model: m ? m.p_home : null,
      modelLabel: m ? (Lab.MODEL_LABELS[m.name] || m.name) : "Elo baseline (v0, untuned)",
      lockText: Lab.lockText(g, now)
    };
  };

  /* The cross-venue note, from market.json's `cross` object (built in jobs/build_site.py). */
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

  /* Zoom window: about 20 cents wide, centered on the data, snapped to 5. */
  Lab.windowFor = function (s) {
    var vals = [];
    [range(s.kalshi), range(s.poly)].forEach(function (r) { if (r) vals.push(r[0], r[1]); });
    if (s.model != null) vals.push(s.model);
    if (!vals.length) return [30, 70];
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    var width = Math.max(20, Math.ceil((hi - lo + 8) / 5) * 5);
    var start = Math.round(((lo + hi) / 2 - width / 2) / 5) * 5;
    start = Math.max(0, Math.min(100 - width, start));
    return [start, start + width];
  };

  Lab.ariaFor = function (s) {
    var kr = range(s.kalshi), pr = range(s.poly);
    var why = function (x) { return x ? "one-sided or empty book" : "no quote in this snapshot"; };
    var t = "Probability " + s.home + " wins, in cents. ";
    t += kr ? "Kalshi bid " + fmt(kr[0]) + " to ask " + fmt(kr[1]) + ". " : "Kalshi: " + why(s.kalshi) + ". ";
    t += pr ? "Polymarket bid " + fmt(pr[0]) + " to ask " + fmt(pr[1]) + ". " : "Polymarket: " + why(s.poly) + ". ";
    if (s.model == null) return t + s.modelLabel + " is not logged yet. " + s.lockText;
    t += s.modelLabel + " " + fmt(s.model);
    if (!kr) return t + ".";
    var g = s.model - mid(kr);
    return t + ", " + (Math.abs(g) < 1 ? "within 1 cent of" : Math.abs(g).toFixed(1) + " cents " + (g > 0 ? "above" : "below")) +
           " the Kalshi mid of " + fmt1(mid(kr)) + ".";
  };

  function scale(win) { var span = win[1] - win[0]; return function (v) { return ((v - win[0]) / span * 100).toFixed(3); }; }
  function ticks(win, step) {
    var P = scale(win), t = "", g = "";
    for (var v = win[0]; v <= win[1] + 0.001; v += step) {
      var edge = v === win[0] ? " first" : v >= win[1] - 0.001 ? " last" : "";
      t += '<span class="tick' + edge + '" style="left:' + P(v) + '%"><b>' + v + "¢</b><i></i></span>";
      if (v > win[0] && v < win[1]) g += '<i class="gl" style="left:' + P(v) + '%"></i>';
    }
    return { ticks: t, grid: g };
  }
  var stepFor = function (win, full) { var s = win[1] - win[0]; return full ? 25 : s <= 25 ? 5 : s <= 50 ? 10 : 25; };
  Lab.axisTicks = function (win, step) { return ticks(win, step).ticks; };

  /* What the model lane says when there is no forecast: derived from the clock, never invented. */
  function lockWords(g, now) {
    if (Lab.lockState(g, now) === "locks") {
      return { head: "Locks", sub: Lab.stamp(new Date(g.lock_utc)), slot: "No forecast yet. It locks 24 hours before kickoff, goes to GitHub, then appears here." };
    }
    var started = new Date(g.kickoff_utc) <= now;
    return { head: "Not logged", sub: "", slot: started ? "Lock time passed and no forecast was logged before kickoff." : "Lock time passed. It shows here once the forecast is pushed to GitHub." };
  }

  /* bid and ask written beside the bar, positioned from the bar's own centre and width */
  function barLabels(c, w, r) {
    var st = ' style="--c:' + c + ";--w:" + w.toFixed(3) + '"';
    return '<em class="lbl l"' + st + ">" + fmt(r[0]) + '</em><em class="lbl r"' + st + ">" + fmt(r[1]) + "</em>";
  }

  /* the one-line answer under the strip: how far the model sits from the Kalshi mid */
  function summary(s) {
    var kr = range(s.kalshi);
    if (s.model == null || !kr) return "";
    var gp = s.model - mid(kr), inside = s.model >= kr[0] && s.model <= kr[1] ? ", inside its bid-ask" : "";
    return '<div class="s-sum"><span class="gap-big num">' + signed(gp) + "¢</span>" +
      (Math.abs(gp) < 1 ? "Model is within 1¢ of the Kalshi mid" : "Model is " + (gp > 0 ? "above" : "below") + " the Kalshi mid") +
      " (" + fmt1(mid(kr)) + "¢) now" + inside + "</div>";
  }

  function block(s, g, now, win, full, zoom) {
    var P = scale(win), T = ticks(win, stepFor(win, full)), span = win[1] - win[0], kr = range(s.kalshi);
    var band = full && zoom ? '<i class="win" style="left:' + P(zoom[0]) + "%;width:" + (P(zoom[1]) - P(zoom[0])).toFixed(3) + '%"></i>' : "";
    var needle = s.model != null ? '<i class="needle" style="left:' + P(s.model) + '%"></i>' : "";
    var h = '<div class="' + (full ? "" : "zoomed") + '"><div class="s-row s-axis"><p class="blk-t">' +
      (full ? "<b>0-100¢</b> Probability " + esc(s.home) + " wins" : "<b>Zoom " + win[0] + "-" + win[1] + "¢</b> Same scale, closer in") +
      '</p><div class="plot">' + T.ticks + "</div>" + (full ? "<span></span>" : "") + "</div>";
    var nm = s.modelLabel.split(" (")[0], sub = (/\((.*)\)/.exec(s.modelLabel) || [0, ""])[1];

    if (s.model != null) {
      h += '<div class="s-row g k-model"><div class="s-lab"><b>' + esc(nm) + "</b>" + (full ? "<span>" + esc(sub) + "</span>" : "") + "</div>" +
        '<div class="plot">' + T.grid + band + '<i class="rail"></i><i class="dia" style="left:' + P(s.model) + '%"></i></div>' +
        (full ? '<div class="s-val"><span class="big">' + Lab.one(s.model) + "¢</span>" + (kr ? '<span class="sm">' + signed(s.model - mid(kr)) + "¢ vs Kalshi mid</span>" : "") + "</div>" : "") + "</div>";
    } else if (full) {
      var w = lockWords(g, now);
      h += '<div class="s-row g k-model"><div class="s-lab"><b>' + esc(nm) + "</b><span>" + esc(sub) + "</span></div>" +
        '<div class="plot">' + T.grid + band + '<div class="slot">' + esc(w.slot) + "</div></div>" +
        '<div class="s-val"><span class="dim">' + esc(w.head) + (w.sub ? "<em>" + esc(w.sub) + "</em>" : "") + "</span></div></div>";
    }
    [["kalshi", "Kalshi", s.kalshi, ""], ["poly", "Polymarket", s.poly, "US exchange"]].forEach(function (m) {
      var r = range(m[2]);
      if (!r && !full) return;
      h += '<div class="s-row g k-' + m[0] + '"><div class="s-lab"><b>' + m[1] + "</b>" + (full && m[3] ? "<span>" + m[3] + "</span>" : "") + "</div>" +
        '<div class="plot">' + T.grid + band + needle + (r
          ? '<i class="rail"></i><i class="bar-m" style="left:' + P(mid(r)) + "%;--w:" + ((r[1] - r[0]) * 100 / span).toFixed(3) + '"></i>' +
            (full ? "" : barLabels(P(mid(r)), (r[1] - r[0]) * 100 / span, r))
          : '<div class="slot">' + (m[2] ? "One-sided or empty book" : "No quote in this snapshot") + "</div>") + "</div>" +
        (full ? '<div class="s-val">' + (r ? '<span class="big">' + Lab.one(mid(r)) + '¢</span><span class="sm"><span class="num">' + Lab.rng(r) + "</span> bid to ask</span>" : '<span class="dim">No quote</span>') + "</div>" : "") + "</div>";
    });
    return h + "</div>";
  }
  Lab.strip = function (el, s, g, now, opts) {
    var win = Lab.windowFor(s), zoomed = !(opts && opts.zoom === false);
    el.innerHTML = '<div role="img" aria-label="' + esc(Lab.ariaFor(s)) + '">' + block(s, g, now, [0, 100], true, zoomed ? win : null) + "</div>" + summary(s) +
      (zoomed ? '<div role="img" aria-label="Zoomed view of the same prices, ' + win[0] + " to " + win[1] + ' cents">' + block(s, g, now, win, false) + "</div>" : "");
  };

  /* Two compact lanes for the week list (Kalshi above Polymarket), model as a diamond on a needle. */
  Lab.mini = function (s) {
    var P = scale([0, 100]), kr = range(s.kalshi), pr = range(s.poly);
    var h = '<div class="mini" role="img" aria-label="' + esc(Lab.ariaFor(s)) + '">';
    [25, 50, 75].forEach(function (v) { h += '<i class="gl" style="left:' + v + '%"></i>'; });
    if (s.model != null) h += '<i class="needle" style="left:' + P(s.model) + '%"></i><i class="dia" style="left:' + P(s.model) + '%;top:50%"></i>';
    [kr, pr].forEach(function (r, i) {
      var q = i ? s.poly : s.kalshi;
      h += '<div class="ln' + (r ? "" : " none-row") + '">' + (r
        ? '<i class="rail"></i><i class="bar-m" style="left:' + P(mid(r)) + "%;--w:" + (r[1] - r[0]).toFixed(3) + '"></i>'
        : '<span class="none">' + (q ? "One-sided book" : "No quote") + "</span>") + "</div>";
    });
    return h + "</div>";
  };
})();
