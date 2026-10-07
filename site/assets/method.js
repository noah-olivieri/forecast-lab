/* Method is prose, plus one live strip (the next game, from the newest saved prices) under
   "Reading the strip" so the explanation sits next to the thing it explains. */
Lab.boot(function (d, now) {
  var el = document.getElementById("method-fig");
  var g = d.games.filter(function (x) { return Date.parse(x.kickoff_utc) > now; })[0];
  if (!el || !g) { if (el) el.hidden = true; return; }
  var s = Lab.stripInput(g, d.market, now);
  el.innerHTML = '<div id="fig-strip"></div><figcaption>Live example: ' + Lab.esc(Lab.team(g.away)) + " at " + Lab.esc(Lab.team(g.home)) +
    ", from the newest saved prices. The diamond is the model once its forecast is logged, each bar is a market's bid to ask range, and the number on the right is the mid.</figcaption>";
  Lab.strip(document.getElementById("fig-strip"), s, g, now, { zoom: false });
});
