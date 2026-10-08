/* Shared pieces: theme toggle, data loading, Pacific-time formatting, lock states, the kickoff
   ticker and the footer. Every page loads this first, then strip.js, then its own script.
   Everything shown comes from data/*.json, which jobs/build_site.py writes from forecasts/,
   config/kickoffs.json and the data branch. Nothing here invents a value. */
(function () {
  "use strict";
  var Lab = (window.Lab = {});
  var TZ = "America/Los_Angeles";

  Lab.TEAMS = {
    ARI: "Arizona", ATL: "Atlanta", BAL: "Baltimore", BUF: "Buffalo", CAR: "Carolina", CHI: "Chicago",
    CIN: "Cincinnati", CLE: "Cleveland", DAL: "Dallas", DEN: "Denver", DET: "Detroit", GB: "Green Bay",
    HOU: "Houston", IND: "Indianapolis", JAX: "Jacksonville", KC: "Kansas City", LA: "LA Rams",
    LAC: "LA Chargers", LV: "Las Vegas", MIA: "Miami", MIN: "Minnesota", NE: "New England",
    NO: "New Orleans", NYG: "NY Giants", NYJ: "NY Jets", PHI: "Philadelphia", PIT: "Pittsburgh",
    SEA: "Seattle", SF: "San Francisco", TB: "Tampa Bay", TEN: "Tennessee", WAS: "Washington"
  };
  Lab.team = function (code) { return Lab.TEAMS[code] || code; };
  Lab.esc = function (s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  var esc = Lab.esc;

  var dayF = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "short" });
  var dateF = new Intl.DateTimeFormat("en-US", { timeZone: TZ, month: "numeric", day: "numeric" });
  var timeF = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", minute: "2-digit" });
  var dayKeyF = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" });
  /* "Thu 5:15 PM" or, with date, "Thu 10/8 5:15 PM" */
  Lab.pt = function (d, withDate) { return dayF.format(d) + (withDate ? " " + dateF.format(d) : "") + " " + timeF.format(d); };
  Lab.time = function (d) { return timeF.format(d); };
  /* "Wed 10/7, 5:15 PM PT": always dated, safe to read days later */
  Lab.stamp = function (d) { return dayF.format(d) + " " + dateF.format(d) + ", " + timeF.format(d) + " PT"; };
  Lab.dayLabel = function (d) { return dayF.format(d) + " " + dateF.format(d); };
  Lab.dayKey = function (d) { return dayKeyF.format(d); };
  /* Whole-unit age of an instant, from UTC timestamps and real milliseconds: no time zone involved. */
  Lab.ago = function (from, now) {
    var h = (now - from) / 3600e3;
    if (h < 1) return Math.max(1, Math.round(h * 60)) + " min";
    if (h < 48) return Math.round(h) + " h";
    return Math.round(h / 24) + " days";
  };

  var fmt = function (n) { return String(+n.toFixed(2)); };
  var fmt1 = function (n) { return String(+n.toFixed(1)); };
  Lab.fmt = fmt; Lab.fmt1 = fmt1;
  /* Values shown as the main number always carry one decimal so columns line up: 45.0, 79.5. */
  Lab.one = function (n) { return n.toFixed(1); };
  Lab.range = function (q) { return q && q.bid != null && q.ask != null ? [q.bid, q.ask] : null; };
  Lab.mid = function (r) { return (r[0] + r[1]) / 2; };
  Lab.rng = function (r) { return fmt(r[0]) + "-" + fmt(r[1]) + "¢"; };
  Lab.signed = function (n) { return (n > 0 ? "+" : n < 0 ? "−" : "") + fmt1(Math.abs(n)); };

  /* "Market prices as of Wed 10/7, 10:18 AM PT." plus a stale warning past 3 hours, judged on the
     older venue. `snaps` is market.json's snapshots ({venue: UTC ISO time}); `now` is Date.now(). */
  Lab.snapshotLine = function (snaps, now) {
    snaps = snaps || {};
    var k = snaps.kalshi ? new Date(snaps.kalshi) : null, p = snaps.polymarket_us ? new Date(snaps.polymarket_us) : null;
    var t = function (d) { return '<time class="t" datetime="' + esc(d.toISOString()) + '">' + esc(Lab.stamp(d)) + "</time>"; };
    if (!k && !p) return "No market snapshot was available when the site was built.";
    var line;
    if (k && p && Math.abs(k - p) > 60e3) line = "Kalshi as of " + t(k) + ", Polymarket as of " + t(p);
    else {
      line = "Market prices as of " + t(k || p);
      if (!k || !p) line += " (" + (k ? "Polymarket" : "Kalshi") + " had no snapshot)";
    }
    var oldest = k && p ? Math.min(k, p) : (k || p);
    return line + "." + (now - oldest > 3 * 3600e3
      ? ' <span class="stale">That is ' + Lab.ago(oldest, now) + " old: prices refresh when the site rebuilds.</span>" : "");
  };

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

  /* --- theme ------------------------------------------------------------------------------ */
  document.addEventListener("click", function (e) {
    if (!e.target.closest || !e.target.closest("#theme")) return;
    var n = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = n;
    try { localStorage.setItem("theme", n); } catch (err) {}
  });

  /* --- data ------------------------------------------------------------------------------- */
  Lab.load = function () {
    return Promise.all(["meta", "games", "market", "forecasts"].map(function (n) {
      return fetch("data/" + n + ".json", { cache: "no-cache" }).then(function (r) {
        if (!r.ok) throw new Error(n + ".json: HTTP " + r.status);
        return r.json();
      });
    })).then(function (a) { return { meta: a[0], games: a[1], market: a[2], forecasts: a[3] }; });
  };

  /* --- ticker: the page's one moving element ---------------------------------------------- */
  var PAUSE = '<svg class="pause" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M216,48V208a16,16,0,0,1-16,16H160a16,16,0,0,1-16-16V48a16,16,0,0,1,16-16h40A16,16,0,0,1,216,48ZM96,32H56A16,16,0,0,0,40,48V208a16,16,0,0,0,16,16H96a16,16,0,0,0,16-16V48A16,16,0,0,0,96,32Z"/></svg>';
  var PLAY = '<svg class="play" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M240,128a15.74,15.74,0,0,1-7.6,13.51L88.32,229.65a16,16,0,0,1-16.2.3A15.86,15.86,0,0,1,64,216.13V39.87a15.86,15.86,0,0,1,8.12-13.82,16,16,0,0,1,16.2.3L232.4,114.49A15.74,15.74,0,0,1,240,128Z"/></svg>';
  function tickList(games, now, hidden) {
    var items = "";
    games.forEach(function (g) {
      var d = new Date(g.kickoff_utc);
      items += "<li><b>" + esc(g.away) + " at " + esc(g.home) + '</b><span class="t">' + Lab.pt(d, d - now > 6 * 864e5) + "</span>" +
        (g.logged ? '<i class="fdot" title="Forecast logged"></i><span class="sr-only">forecast logged</span>' : "") + "</li>";
    });
    return '<ul class="tk-list"' + (hidden ? ' aria-hidden="true"' : "") + ">" + items + "</ul>";
  }
  Lab.ticker = function (games, now) {
    var root = document.getElementById("ticker");
    if (!root) return;
    var shown = games.filter(function (g) { return Date.parse(g.kickoff_utc) > now - 3 * 3600e3; }).slice(0, 15);
    root.setAttribute("role", "region");
    root.setAttribute("aria-label", "Upcoming kickoffs, Pacific time");
    if (!shown.length) {
      root.innerHTML = '<div class="tk-label">Upcoming kickoffs, PT</div><div class="tk-run tk-empty">No games left on the schedule</div>';
      return;
    }
    var anyLogged = shown.some(function (g) { return g.logged; });
    root.innerHTML =
      '<div class="tk-label">Upcoming kickoffs, PT</div>' +
      '<div class="tk-run" id="tk-run" tabindex="0" aria-label="Upcoming kickoffs, scrollable"><div class="tk-belt" id="tk-belt">' +
      tickList(shown, now, false) + tickList(shown, now, true) + "</div></div>" +
      '<div class="tk-key' + (anyLogged ? " on" : "") + '"><i class="fdot"></i>Forecast logged</div>' +
      '<button class="tk-btn" id="tk-btn" type="button" aria-label="Pause ticker" aria-pressed="false">' + PAUSE + PLAY + "</button>";
    var belt = document.getElementById("tk-belt"), btn = document.getElementById("tk-btn");
    var SPEED = 30; // px per second: slow enough to read a matchup at a glance
    function setSpeed() { var w = belt.firstElementChild.offsetWidth; if (w) belt.style.setProperty("--dur", (w / SPEED).toFixed(1) + "s"); }
    setSpeed();
    addEventListener("load", setSpeed);
    btn.addEventListener("click", function () {
      var p = root.classList.toggle("paused");
      btn.setAttribute("aria-pressed", p);
      btn.setAttribute("aria-label", p ? "Play ticker" : "Pause ticker");
    });
  };

  /* --- footer ----------------------------------------------------------------------------- */
  Lab.footer = function (meta) {
    var el = document.getElementById("built");
    if (!el || !meta) return;
    el.innerHTML = "Built " + esc(Lab.stamp(new Date(meta.built_utc))) + ' from <a href="' + esc(meta.commit_url) + '">' + esc(meta.commit.slice(0, 7)) + "</a>";
  };

  /* --- boot ------------------------------------------------------------------------------- */
  Lab.boot = function (render) {
    var now = Date.now();
    Lab.load().then(function (d) {
      Lab.ticker(d.games, now);
      Lab.footer(d.meta);
      render(d, now);
      document.documentElement.dataset.ready = "1";
    }).catch(function (err) {
      var box = document.getElementById("app");
      if (box) {
        box.innerHTML = '<p class="msg">The data files did not load (' + esc(err.message) +
          '). If you are running this locally, build them with <code>uv run python jobs/build_site.py</code> and serve the <code>site</code> folder over HTTP.</p>';
      }
      var t = document.getElementById("ticker");
      if (t) t.hidden = true;
      document.documentElement.dataset.ready = "error";
    });
  };
})();
