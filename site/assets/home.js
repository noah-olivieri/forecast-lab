/* Home: the next game as a strip, plus project status. All numbers come from site/data/*.json,
   which jobs/build_site.py writes from forecasts/, config/kickoffs.json and the data branch. */
Lab.boot(function (d, now) {
  var S = Lab.strip, esc = Lab.esc;
  var upcoming = d.games.filter(function (g) { return Date.parse(g.kickoff_utc) > now; });
  var g = upcoming[0];

  var nextEl = document.getElementById("next");
  var title = document.getElementById("feat"), sub = document.getElementById("hero-sub");
  var howto = document.getElementById("hero-howto");

  if (!g) {
    nextEl.textContent = "";
    title.textContent = "No games left on the schedule";
    sub.textContent = "The schedule in config/kickoffs.json has no future kickoffs.";
  } else {
    var kick = new Date(g.kickoff_utc);
    nextEl.innerHTML = "<b>Next:</b> " + esc(g.away) + " at " + esc(g.home) + ", " + Lab.pt(kick, kick - now > 6 * 864e5) + " PT";
    title.textContent = Lab.team(g.away) + " at " + Lab.team(g.home);

    var s = Lab.stripInput(g, d.market, now);
    sub.innerHTML = Lab.snapshotLine(d.market.snapshots, now);

    S.build(document.getElementById("hero-plots"), s);
    document.getElementById("hero-gap").innerHTML = S.gap(s);
    var cross = Lab.crossNote(((d.market.games || {})[g.id] || {}).cross, s);
    var xel = document.getElementById("hero-cross");
    xel.innerHTML = cross ? "<p>" + cross + "</p>" : "";
    xel.hidden = !cross;

    var parts = [];
    parts.push("<p><b>How to read it.</b> Each bar spans a market's bid (the highest price a buyer is offering) and ask (the lowest price a seller will take).");
    var mids = [];
    if (S.range(s.kalshi)) mids.push("Kalshi " + S.fmt1(S.mid(S.range(s.kalshi))) + "¢");
    if (S.range(s.poly)) mids.push("Polymarket " + S.fmt1(S.mid(S.range(s.poly))) + "¢");
    if (mids.length) parts.push(" The mid is halfway between the two: " + mids.join(", ") + ".");
    if (s.poly && s.poly.flipped) parts.push(" Polymarket quotes " + esc(s.away) + ", so " + esc(s.home) + " is 100¢ minus that.");
    parts.push(" Polymarket here is its US exchange.</p>");
    howto.innerHTML = parts.join("");
    howto.hidden = false;
  }

  var n = d.meta.games_logged;
  document.getElementById("st-logged").textContent = String(n);
  var note = document.getElementById("st-logged-note");
  var nextLock = upcoming.filter(function (x) { return Lab.lockState(x, now) === "locks"; })[0];
  if (n === 0 && nextLock) {
    var when = Lab.stamp(new Date(nextLock.lock_utc)), who = Lab.team(nextLock.away) + " at " + Lab.team(nextLock.home);
    note.textContent = (Lab.lockState(g, now) === "missed"
      ? "The next to lock is " + who + ", " + when + ". "
      : "The first, " + who + ", locks " + when + ". ") +
      "It goes to GitHub before kickoff. GitHub's push time is the receipt, and any later change shows in the history.";
  } else if (n === 0) {
    note.textContent = "Forecasts appear here once their files are pushed to GitHub.";
  } else {
    note.innerHTML = 'Each was pushed to GitHub before kickoff. <a href="log.html">See the forecast log</a> for the prices and commits.';
  }
});
