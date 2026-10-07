/* Shared pieces: theme toggle, data loading, Pacific-time formatting, the kickoff ticker and the
   footer. Every page loads this first, then strip.js, then its own script. No build step. */
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

  var dayF = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "short" });
  var dateF = new Intl.DateTimeFormat("en-US", { timeZone: TZ, month: "numeric", day: "numeric" });
  var timeF = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", minute: "2-digit" });
  var dayKeyF = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" });
  Lab.date = function (s) { return new Date(s); };
  /* "Thu 5:15 PM" or, with date, "Thu 10/8 5:15 PM" */
  Lab.pt = function (d, withDate) {
    return dayF.format(d) + (withDate ? " " + dateF.format(d) : "") + " " + timeF.format(d);
  };
  /* "Wed 10/7, 5:15 PM PT": always dated, safe to read days later */
  Lab.stamp = function (d) { return dayF.format(d) + " " + dateF.format(d) + ", " + timeF.format(d) + " PT"; };
  Lab.dayLabel = function (d) { return dayF.format(d) + " " + dateF.format(d); };
  Lab.dayKey = function (d) { return dayKeyF.format(d); };
  Lab.ago = function (from, now) {
    var h = (now - from) / 3600e3;
    if (h < 1) return Math.max(1, Math.round(h * 60)) + " min";
    if (h < 48) return Math.round(h) + " h";
    return Math.round(h / 24) + " days";
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
    var names = ["meta", "games", "market", "forecasts"];
    return Promise.all(names.map(function (n) {
      return fetch("data/" + n + ".json", { cache: "no-cache" }).then(function (r) {
        if (!r.ok) throw new Error(n + ".json: HTTP " + r.status);
        return r.json();
      });
    })).then(function (a) { return { meta: a[0], games: a[1], market: a[2], forecasts: a[3] }; });
  };

  /* --- ticker ----------------------------------------------------------------------------- */
  var PAUSE = '<svg class="pause" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M216,48V208a16,16,0,0,1-16,16H160a16,16,0,0,1-16-16V48a16,16,0,0,1,16-16h40A16,16,0,0,1,216,48ZM96,32H56A16,16,0,0,0,40,48V208a16,16,0,0,0,16,16H96a16,16,0,0,0,16-16V48A16,16,0,0,0,96,32Z"/></svg>';
  var PLAY = '<svg class="play" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M240,128a15.74,15.74,0,0,1-7.6,13.51L88.32,229.65a16,16,0,0,1-16.2.3A15.86,15.86,0,0,1,64,216.13V39.87a15.86,15.86,0,0,1,8.12-13.82,16,16,0,0,1,16.2.3L232.4,114.49A15.74,15.74,0,0,1,240,128Z"/></svg>';

  function tickerList(games, now, hidden) {
    var items = "";
    games.forEach(function (g) {
      var d = new Date(g.kickoff_utc);
      items += "<li><b>" + Lab.esc(g.away) + " at " + Lab.esc(g.home) + '</b><span class="t">' +
        Lab.pt(d, d - now > 6 * 864e5) + "</span>" +
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
      root.innerHTML = '<div class="tk-label">Upcoming kickoffs, PT</div><div class="tk-run" style="display:flex;align-items:center;padding-left:16px">No games left on the schedule</div>';
      return;
    }
    var anyLogged = shown.some(function (g) { return g.logged; });
    root.innerHTML =
      '<div class="tk-label">Upcoming kickoffs, PT</div>' +
      '<div class="tk-run" id="tk-run" tabindex="0" aria-label="Upcoming kickoffs, scrollable"><div class="tk-belt" id="tk-belt">' +
      tickerList(shown, now, false) + tickerList(shown, now, true) + "</div></div>" +
      '<div class="tk-key' + (anyLogged ? " on" : "") + '"><i class="fdot"></i>Forecast logged</div>' +
      '<button class="tk-btn" id="tk-btn" type="button" aria-label="Pause ticker" aria-pressed="false">' + PAUSE + PLAY + "</button>";

    var belt = document.getElementById("tk-belt"), btn = document.getElementById("tk-btn");
    var SPEED = 30; // px per second: slow enough to read a matchup at a glance
    function setSpeed() {
      var w = belt.firstElementChild.offsetWidth;
      if (w) belt.style.setProperty("--dur", (w / SPEED).toFixed(1) + "s");
    }
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
    el.innerHTML = 'Built ' + Lab.esc(Lab.stamp(new Date(meta.built_utc))) + ' from <a href="' +
      Lab.esc(meta.commit_url) + '">' + Lab.esc(meta.commit.slice(0, 7)) + "</a>";
  };

  /* --- boot ------------------------------------------------------------------------------- */
  Lab.boot = function (render) {
    var now = Date.now();
    Lab.load().then(function (d) {
      Lab.ticker(d.games, now);
      Lab.footer(d.meta);
      render(d, now);
    }).catch(function (err) {
      var box = document.getElementById("app");
      if (box) {
        box.innerHTML = '<p class="msg">The data files did not load (' + Lab.esc(err.message) +
          '). If you are running this locally, build them with <code>uv run python jobs/build_site.py</code> and serve the <code>site</code> folder over HTTP.</p>';
      }
      var t = document.getElementById("ticker");
      if (t) t.hidden = true;
    });
  };
})();
