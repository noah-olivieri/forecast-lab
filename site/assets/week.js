/* This week: every game in the NFL week of the next kickoff, as compact strips on one axis. */
Lab.boot(function (d, now) {
  var esc = Lab.esc, S = Lab.strip;
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
  document.getElementById("wk-axis").innerHTML = S.ticks100();

  sub.innerHTML = Lab.snapshotLine(d.market.snapshots, now) + " Each strip runs from 0¢ to 100¢.";

  var html = "", day = null;
  games.forEach(function (g) {
    var kick = new Date(g.kickoff_utc), key = Lab.dayKey(kick);
    if (key !== day) {
      if (day !== null) html += "</ul>";
      html += '<h3 class="day">' + esc(Lab.dayLabel(kick)) + '</h3><ul class="glist">';
      day = key;
    }
    var s = Lab.stripInput(g, d.market, now), over = kick < now;
    var cross = Lab.crossNote(((d.market.games || {})[g.id] || {}).cross, s);
    var q = function (r, name, cls) {
      return '<div class="' + cls + '"><span class="nm">' + name + '</span><span class="num">' +
        (r ? S.rng(r) : "no quote") + "</span></div>";
    };
    var mdl = g.model ? '<div class="k-model"><span class="nm">Model</span><span class="num">' + S.fmt(g.model.p_home) + "¢</span></div>" : "";
    var st = Lab.lockState(g, now);
    var state = st === "logged" ? '<span class="state"><i class="fdot"></i>Forecast logged</span>'
      : st === "missed" ? "<span>Not logged</span>"
      : "<span>Locks " + esc(Lab.pt(new Date(g.lock_utc), true)) + " PT</span>";
    html += '<li class="game"><div class="g-who"><b>' + esc(g.away) + " at " + esc(g.home) + "</b><span>" +
      esc(Lab.pt(kick)) + " PT" + (over ? ", started" : "") + "</span>" + state + "</div>" + S.mini(s) +
      '<div class="g-nums">' + mdl + q(S.range(s.kalshi), "Kalshi", "k-kalshi") + q(S.range(s.poly), "Polymarket", "k-poly") + "</div>" +
      (cross ? '<div class="xgap"><p>' + cross + "</p></div>" : "") + "</li>";
  });
  body.innerHTML = html + "</ul>";
});
