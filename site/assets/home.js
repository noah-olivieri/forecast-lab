/* Home: the next game as a strip, plus project status. All numbers come from data/*.json. */
Lab.boot(function (d, now) {
  var esc = Lab.esc, fmt1 = Lab.fmt1, range = Lab.range, mid = Lab.mid;
  var upcoming = d.games.filter(function (g) { return Date.parse(g.kickoff_utc) > now; });
  var g = upcoming[0];
  var noteRow = function (label, html) { return '<div class="note-row"><b>' + label + "</b><p>" + html + "</p></div>"; };

  if (!g) {
    document.getElementById("feat").textContent = "No games left on the schedule";
    document.getElementById("hero-sub").textContent = "The schedule in config/kickoffs.json has no future kickoffs.";
  } else {
    var kick = new Date(g.kickoff_utc), s = Lab.stripInput(g, d.market, now);
    document.getElementById("feat").textContent = Lab.team(g.away) + " at " + Lab.team(g.home);
    document.getElementById("hero-sub").innerHTML = "Next game, kickoff " + esc(Lab.pt(kick, true)) + " PT. " + Lab.snapshotLine(d.market.snapshots, now);
    Lab.strip(document.getElementById("hero-plots"), s, g, now);
    document.getElementById("legend").innerHTML =
      '<span class="k-model"><i></i><b>Model</b> Elo baseline, one value</span>' +
      '<span class="k-mkt"><i></i><b>Market</b> bid to ask range</span>' +
      (s.model != null ? '<span class="k-needle"><i></i>Dashed line: model position</span>' : "") +
      '<span class="k-zoom"><i></i>Shaded: zoomed below</span>';

    var notes = "", kr = range(s.kalshi), pr = range(s.poly);
    if (s.cross) notes += noteRow("Cross-venue gap", Lab.crossNote(s.cross, s).replace(/^<b>Cross-venue gap<\/b> /, ""));
    var mids = [];
    if (kr) mids.push("Kalshi " + fmt1(mid(kr)) + "¢");
    if (pr) mids.push("Polymarket " + fmt1(mid(pr)) + "¢");
    notes += noteRow("How to read it", "Each bar spans a market's bid (the highest price a buyer is offering) and ask (the lowest price a seller will take)." +
      (mids.length ? " The mid is halfway between the two: " + mids.join(", ") + "." : "") +
      (s.poly && s.poly.flipped ? " Polymarket quotes " + esc(s.away) + ", so " + esc(s.home) + " is 100¢ minus that." : "") +
      " Polymarket here is its US exchange.");
    document.getElementById("hero-notes").innerHTML = notes;
  }

  var n = d.meta.games_logged, note = document.getElementById("st-logged-note");
  document.getElementById("st-logged").textContent = String(n);
  var nl = upcoming.filter(function (x) { return Lab.lockState(x, now) === "locks"; })[0];
  var missed = g && Lab.lockState(g, now) === "missed";
  if (n === 0 && nl) {
    note.textContent = (missed ? "The next to lock is " : "The first, ") + Lab.team(nl.away) + " at " + Lab.team(nl.home) +
      (missed ? ", " : ", locks ") + Lab.stamp(new Date(nl.lock_utc)) +
      ". It goes to GitHub before kickoff. GitHub's push time is the receipt, and any later change shows in the history.";
  } else if (n === 0) {
    note.textContent = "Forecasts appear here once their files are pushed to GitHub.";
  } else {
    note.innerHTML = 'Each was pushed to GitHub before kickoff. <a href="log.html">See the forecast log</a> for the prices and commits.';
  }
});
