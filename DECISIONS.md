# Decisions

## 2026-10-08: One game is not evidence (TB@DAL pilot)

Decision: No conclusion from single games, including the TB@DAL pilot. The 1,000 settled
game threshold stays.

What happened: TB won 24-16 at DAL, so y = 0 (unofficial until nflverse settles it).
Elo v0 had DAL at 67.8%, Kalshi 79.5%, Polymarket 79.6%. Elo scored better on Brier
(0.460 vs 0.632) and log loss (1.133 vs 1.585).

My reasoning (my words, typos fixed): "This result can't tell me Elo is better because it
was a severe upset, which meant that my model was just less confident. It doesn't
necessarily mean that it was more accurate because it's only scored on the log and Brier
scale. The less confident model would technically score higher, not necessarily making it
better."

Review note (from Claude): An 80% favorite loses about 1 game in 5, so this wasn't a
severe upset. Brier and log loss are the right metrics; the problem is one game. If the
market's 79.5% were the true probability, the market would beat Elo by about 0.014 Brier
per game on average. This one game swung 0.17 the other way.

Action: None. The game gets settled and scored through Phase B/C like any other.

## 2026-10-08: Keep frozen Elo; RF-001 does not replace it

Decision: Elo v0 stays the baseline. RF-001 is not promoted.

What happened: First reconstructed backtest (run rf001-reconstructed-2006-2023-first-v1),
2015-2023 outer seasons. All games (2,458): RF-001 Brier 0.2260, Elo 0.2237. Paired
difference RF-001 minus Elo is +0.0022, 95% CI [-0.0003, +0.0056], so no clear difference.
Decisive games with a historical moneyline (2,448): moneyline 0.2137, Elo 0.2245,
RF-001 0.2269. RF-001 minus moneyline is +0.0132, 95% CI [+0.0102, +0.0186].

My reasoning (my words): "Both models only use final scores of past games and the market
also knows starting players, starting quarterbacks, and injury reports."

Caveats: The moneyline's book and timing are unknown and it is probably close to closing,
so this is not a T-24h comparison. The 2024-2025 holdout was not touched. A known defect in
the sensitivity diagnostic (200 repeat counts truncated by one draw) changes no flags; it is
disclosed in the report and was not rerun.
