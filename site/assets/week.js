/* This week: every game in the NFL week of the next kickoff, as a ledger with compact strips. */
Lab.boot(function (d, now) {
  var esc = Lab.esc, fmt = Lab.fmt, fmt1 = Lab.fmt1, range = Lab.range, mid = Lab.mid;
  var next = d.games.filter(function (g) { return Date.parse(g.kickoff_utc) > now; })[0];
  var last = d.games[d.games.length - 1];
  var wk = (next || last || {}).week;
  var games = d.games.filter(function (g) { return g.week === wk; });
  var h = document.getElementById("week-h"), sub = document.getElementById("wk-sub"), body = document.getElementById("wk-body");
  if (!games.length) {
    h.textContent = "This week";
    sub.textContent = "No games on the schedule.";
    return;
  }
  h.textContent = "Week " + wk;
  var hasModel = games.some(function (g) { return g.model; });
  document.querySelector(".wk").classList.toggle("no-model", !hasModel);
  document.getElementById("wk-legend").innerHTML =
    (hasModel ? '<span class="k-model"><i></i><b>Model</b> Elo baseline, one value</span>' : "") +
    '<span class="k-mkt"><i></i><b>Market</b> bid to ask range, Kalshi on top, Polymarket below</span>';
  sub.innerHTML = Lab.snapshotLine(d.market.snapshots, now) + " Each strip runs from 0¢ to 100¢. Times are Pacific." +
    (hasModel ? "" : " Model values appear here 24 hours before each kickoff.");
  document.getElementById("wk-axis").innerHTML = Lab.axisTicks([0, 100], 25);

  var cell = function (r, label) {
    return '<div class="nm" data-l="' + label + '">' + (r
      ? '<span class="m" title="' + label + " bid " + fmt(r[0]) + ", ask " + fmt(r[1]) + '">' + Lab.one(mid(r)) + "</span><small>" + fmt(r[0]) + "-" + fmt(r[1]) + "</small>"
      : '<span class="dim"><span class="sr-only">no quote</span><span aria-hidden="true">-</span></span>') + "</div>";
  };
  var html = "", day = null;
  games.forEach(function (g) {
    var kick = new Date(g.kickoff_utc), key = Lab.dayKey(kick), first = key !== day;
    day = key;
    var s = Lab.stripInput(g, d.market, now), st = Lab.lockState(g, now), dl = Lab.dayLabel(kick).split(" ");
    var state = st === "logged" ? '<span class="st-logged"><i class="fdot"></i>Forecast logged</span>'
      : st === "missed" ? "<span>Not logged</span>"
      : "<span>Locks " + esc(Lab.pt(new Date(g.lock_utc), true)) + "</span>";
    html += '<div class="led led-row"><div class="led-day">' + (first ? esc(dl[0]) + "<small>" + esc(dl[1]) + "</small>" : "") + "</div>" +
      '<div class="g-who"><b>' + esc(g.away) + " at " + esc(g.home) + "</b><span>" + esc(Lab.time(kick)) + (kick < now ? ", started" : "") + "</span>" + state + "</div>" +
      Lab.mini(s) +
      '<div class="g-nums">' + (s.model != null
        ? '<div class="nm mcol k-model" data-l="Model"><span class="m">' + Lab.one(s.model) + "</span></div>"
        : '<div class="nm mcol" data-l="Model"><span class="dim"><span class="sr-only">no model</span><span aria-hidden="true">-</span></span></div>') +
      cell(range(s.kalshi), "Kalshi") + cell(range(s.poly), "Polymarket") + "</div>" +
      (s.cross ? '<div class="x-row"><p>' + Lab.crossNote(s.cross, s) + "</p></div>" : "") + "</div>";
  });
  body.innerHTML = html;
});
