/* Forecast log: one row per logged game, straight from the CSVs in forecasts/. */
Lab.boot(function (d, now) {
  var esc = Lab.esc, S = Lab.strip;
  var files = d.forecasts.files, rows = d.forecasts.rows;
  var fileBy = {};
  files.forEach(function (f) { fileBy[f.path] = f; });
  var gameBy = {};
  d.games.forEach(function (g) { gameBy[g.id] = g; });

  var c = function (x) { return x == null ? '<span class="none">none</span>' : '<span class="num">' + S.fmt1(x) + "¢</span>"; };
  var quote = function (r) {
    if (!r || r.market_bid == null || r.market_ask == null) return '<span class="none">no quote</span>';
    return c((r.market_bid + r.market_ask) / 2) + '<span class="sub num">' + S.fmt(r.market_bid) + "–" + S.fmt(r.market_ask) + "¢</span>";
  };

  // Group rows by file and game: model rows share one set of probabilities.
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

  if (!order.length) {
    sub.textContent = "Nothing logged yet.";
    var g0 = upcoming[0];
    body.innerHTML = '<p class="msg" style="padding-bottom:4px">No forecast file is in <code>forecasts/</code> on <code>main</code> yet. ' +
      (g0 ? "The first, " + esc(Lab.team(g0.away)) + " at " + esc(Lab.team(g0.home)) + ", locks " + esc(Lab.stamp(new Date(g0.lock_utc))) + ". " : "") +
      "It shows up here once the file is pushed, with the prices it was compared against and a link to its commit.</p>";
  } else {
    sub.textContent = order.length + " game" + (order.length === 1 ? "" : "s") + " in " + files.length + " file" + (files.length === 1 ? "" : "s") +
      ". Every number is the home team's win probability.";
    var html = '<table class="tbl"><thead><tr><th scope="col">Game</th><th scope="col" class="r">Elo baseline</th><th scope="col" class="r">Home rate</th>' +
      '<th scope="col" class="r">Kalshi</th><th scope="col" class="r">Polymarket</th><th scope="col">Logged</th><th scope="col">Proof</th></tr></thead><tbody>';
    order.forEach(function (k) {
      var gr = groups[k], f = fileBy[gr.file], g = gameBy[gr.game] || {};
      var by = function (model, venue) {
        return gr.rows.filter(function (r) { return r.model === model && (!venue || r.venue === venue); })[0];
      };
      var elo = by("elo"), home = by("home_rate");
      var kal = by("market_mid", "kalshi"), pol = by("market_mid", "polymarket_us");
      var any = gr.rows[0], kick = new Date(any.kickoff_ts), made = new Date(any.created_ts);
      var proof;
      if (f.status === "pushed" && any.before_kickoff) {
        proof = '<span class="chip"><i class="fdot"></i>On GitHub</span> <a class="sub" href="' + esc(f.commit_url) + '">commit ' + esc(f.commit.slice(0, 7)) + "</a>";
      } else if (f.status === "pushed") {
        proof = '<span class="chip warn">Logged after kickoff</span> <a class="sub" href="' + esc(f.commit_url) + '">commit ' + esc(f.commit.slice(0, 7)) + "</a>";
      } else if (f.status === "committed") {
        proof = '<span class="chip warn">Committed, not on main</span><span class="sub">Not counted until it is pushed.</span>';
      } else {
        proof = '<span class="chip warn">Not committed</span><span class="sub">Not counted until it is pushed.</span>';
      }
      var who = g.away ? Lab.team(g.away) + " at " + Lab.team(g.home) : gr.game;
      html += "<tr><td class=\"who\" data-label=\"Game\"><b>" + esc(who) + '</b><span class="sub">Kickoff ' + esc(Lab.stamp(kick)) + "</span></td>" +
        '<td class="r" data-label="Elo baseline">' + c(elo && elo.p_yes) + '<span class="sub">' + esc(elo ? elo.model_version : "") + "</span></td>" +
        '<td class="r" data-label="Home rate">' + c(home && home.p_yes) + "</td>" +
        '<td class="r" data-label="Kalshi">' + quote(kal) + "</td>" +
        '<td class="r" data-label="Polymarket">' + quote(pol) + "</td>" +
        '<td data-label="Logged">' + esc(Lab.stamp(made)) + '<span class="sub">prices from ' + esc(Lab.stamp(new Date(any.snapshot_ts))) + "</span></td>" +
        '<td class="proof" data-label="Proof">' + proof + "</td></tr>";
    });
    html += "</tbody></table>";
    html += '<ul class="files">' + files.map(function (f) {
      return "<li>" + (f.blob_url ? '<a href="' + esc(f.blob_url) + '">' + esc(f.path) + "</a>" : "<span>" + esc(f.path) + "</span>") +
        "<span>" + f.rows + " rows</span>" + (f.commit_ts ? "<span>committed " + esc(Lab.stamp(new Date(f.commit_ts))) + "</span>" : "") + "</li>";
    }).join("") + "</ul>";
    body.innerHTML = html;
  }
  if (d.forecasts.files.length && pushed < files.length) {
    sub.textContent += " " + (files.length - pushed) + " not on main yet.";
  }

  var locks = upcoming.filter(function (g) { return !g.logged; }).slice(0, 6);
  document.getElementById("locks").innerHTML = locks.length ? locks.map(function (g) {
    var lock = new Date(g.lock_utc), past = lock < now;
    return "<li><b>" + esc(Lab.team(g.away)) + " at " + esc(Lab.team(g.home)) + "</b><span>" +
      (past ? "Lock time passed " + esc(Lab.stamp(lock)) : "Locks " + esc(Lab.stamp(lock))) + "</span></li>";
  }).join("") : "<li><span>No more games on the schedule.</span></li>";
});
