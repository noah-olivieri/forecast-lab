/* Forecast log: one row per logged game, straight from the CSVs in forecasts/. */
Lab.boot(function (d, now) {
  var esc = Lab.esc, fmt = Lab.fmt;
  var files = d.forecasts.files, rows = d.forecasts.rows, fileBy = {}, gameBy = {};
  files.forEach(function (f) { fileBy[f.path] = f; });
  d.games.forEach(function (g) { gameBy[g.id] = g; });

  var dash = '<span class="dim"><span class="sr-only">none</span><span aria-hidden="true">-</span></span>';
  var val = function (x, cls) { return x == null ? dash : '<span class="m ' + (cls || "") + '">' + Lab.one(x) + "</span>"; };
  var quote = function (r) {
    if (!r || r.market_bid == null || r.market_ask == null) return dash;
    return val((r.market_bid + r.market_ask) / 2) + "<small>" + fmt(r.market_bid) + "-" + fmt(r.market_ask) + "</small>";
  };

  var groups = {}, order = [];
  rows.forEach(function (r) {
    var k = r.file + "|" + r.game_id;
    if (!groups[k]) { groups[k] = { file: r.file, game: r.game_id, rows: [] }; order.push(k); }
    groups[k].rows.push(r);
  });
  order.sort(function (a, b) {
    var ra = groups[a].rows[0].created_ts, rb = groups[b].rows[0].created_ts;
    return ra < rb ? 1 : ra > rb ? -1 : 0;
  });

  var sub = document.getElementById("log-sub"), body = document.getElementById("log-body");
  var pushed = files.filter(function (f) { return f.status === "pushed"; }).length;
  var upcoming = d.games.filter(function (g) { return Date.parse(g.kickoff_utc) > now; });
  var locking = upcoming.filter(function (g) { return Lab.lockState(g, now) === "locks"; });

  if (!order.length) {
    sub.textContent = "Nothing logged yet.";
    var g0 = locking[0];
    body.innerHTML = '<p class="msg">No forecast file is in <code>forecasts/</code> on <code>main</code> yet. ' +
      (g0 ? "The next to lock, " + esc(Lab.team(g0.away)) + " at " + esc(Lab.team(g0.home)) + ", locks " + esc(Lab.stamp(new Date(g0.lock_utc))) + ". " : "") +
      "A forecast shows up here once its file is pushed, with the prices it was compared against and a link to its commit.</p>";
  } else {
    sub.textContent = order.length + " game" + (order.length === 1 ? "" : "s") + " in " + files.length + " file" + (files.length === 1 ? "" : "s") +
      ". Every number is the home team's win probability, in cents.";
    var html = '<div class="tbl-scroll" tabindex="0" role="region" aria-label="Logged forecasts, scrolls sideways"><table class="tbl"><thead><tr><th scope="col">Game</th>' +
      '<th scope="col" class="r">Elo baseline</th><th scope="col" class="r">Home rate</th><th scope="col" class="r">Kalshi</th><th scope="col" class="r">Polymarket</th>' +
      '<th scope="col">Logged</th><th scope="col">Proof</th></tr></thead><tbody>';
    order.forEach(function (k) {
      var gr = groups[k], f = fileBy[gr.file], g = gameBy[gr.game] || {};
      var by = function (model, venue) { return gr.rows.filter(function (r) { return r.model === model && (!venue || r.venue === venue); })[0]; };
      var elo = by("elo"), home = by("home_rate"), kal = by("market_mid", "kalshi"), pol = by("market_mid", "polymarket_us");
      var any = gr.rows[0], kick = new Date(any.kickoff_ts), made = new Date(any.created_ts), proof;
      var link = f.commit ? ' <a class="sub" href="' + esc(f.commit_url) + '">commit ' + esc(f.commit.slice(0, 7)) + "</a>" : "";
      if (f.status === "pushed" && any.before_kickoff) proof = '<span class="chip"><i class="fdot"></i>On GitHub</span>' + link;
      else if (f.status === "pushed") proof = '<span class="chip warn">Logged after kickoff</span>' + link;
      else if (f.status === "committed") proof = '<span class="chip warn">Committed, not on main</span><span class="sub">Not counted until it is pushed.</span>';
      else proof = '<span class="chip warn">Not committed</span><span class="sub">Not counted until it is pushed.</span>';
      var who = g.away ? Lab.team(g.away) + " at " + Lab.team(g.home) : gr.game;
      html += '<tr><td class="who" data-label="Game"><b>' + esc(who) + '</b><span class="sub">Kickoff ' + esc(Lab.stamp(kick)) + "</span></td>" +
        '<td class="r" data-label="Elo baseline">' + val(elo && elo.p_yes, "k-model") + '<small>' + esc(elo ? elo.model_version : "") + "</small></td>" +
        '<td class="r" data-label="Home rate">' + val(home && home.p_yes) + "</td>" +
        '<td class="r" data-label="Kalshi">' + quote(kal) + "</td>" +
        '<td class="r" data-label="Polymarket">' + quote(pol) + "</td>" +
        '<td data-label="Logged">' + esc(Lab.stamp(made)) + '<span class="sub">prices from ' + esc(Lab.stamp(new Date(any.snapshot_ts))) + "</span></td>" +
        '<td class="proof" data-label="Proof">' + proof + "</td></tr>";
    });
    html += "</tbody></table></div>";
    html += '<ul class="files">' + files.map(function (f) {
      return "<li>" + (f.blob_url ? '<a href="' + esc(f.blob_url) + '">' + esc(f.path) + "</a>" : "<span>" + esc(f.path) + "</span>") +
        "<span>" + f.rows + " rows</span>" + (f.commit_ts ? "<span>committed " + esc(Lab.stamp(new Date(f.commit_ts))) + "</span>" : "") + "</li>";
    }).join("") + "</ul>";
    body.innerHTML = html;
    if (pushed < files.length) sub.textContent += " " + (files.length - pushed) + " not on main yet.";
  }

  // Only games whose lock time is still ahead. A game past its lock with no forecast is not
  // "coming up"; the Week page marks it "Not logged".
  document.getElementById("locks").innerHTML = locking.slice(0, 6).length ? locking.slice(0, 6).map(function (g) {
    return "<li><b>" + esc(Lab.team(g.away)) + " at " + esc(Lab.team(g.home)) + "</b><span>Locks " + esc(Lab.stamp(new Date(g.lock_utc))) + "</span></li>";
  }).join("") : "<li><span>No more locks on the schedule.</span></li>";
});
