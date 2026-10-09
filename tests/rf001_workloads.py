"""Invented workloads shared by RF-001 review tests and engineering measurements."""

from datetime import UTC, datetime, timedelta

from rf001_fixtures import label, schedule


def invented_league(seasons=2):
    schedules, labels = [], []
    order = list(range(32))
    for season in range(2011, 2011 + seasons):
        for week in range(1, 18):
            kickoff = datetime(season, 9, 1, 17, tzinfo=UTC) + timedelta(days=7 * (week - 1))
            for slot in range(16):
                home, away = order[slot], order[-slot - 1]
                if week % 2:
                    home, away = away, home
                gid = f"invented-{season}-{week:02d}-{slot:02d}"
                hs = 24 + 2 * (home % 8) - 7 + 2 * (away // 4) - 7 + 2 + ((week + slot) % 5 - 2)
                aws = 24 + 2 * (away % 8) - 7 + 2 * (home // 4) - 7 + ((week - slot) % 5 - 2)
                schedules.append(
                    schedule(
                        gid, kickoff, week=week, home_team=f"T{home:02d}", away_team=f"T{away:02d}"
                    )
                )
                labels.append(label(gid, kickoff, home_score=hs, away_score=aws))
            order = [order[0], order[-1], *order[1:-1]]
    return schedules, labels


def known_effect_league():
    schedules, labels = [], []
    offense = {f"T{i:02d}": 2 * (i % 8) - 7 for i in range(32)}
    defense = {f"T{i:02d}": 2 * (i // 4) - 7 for i in range(32)}
    order = list(offense)
    for week in range(31):
        kickoff = datetime(2011, 1, 1, 17, tzinfo=UTC) + timedelta(days=7 * week)
        for slot in range(16):
            home, away = order[slot], order[-slot - 1]
            gid = f"known-{home}-{away}"
            schedules.append(
                schedule(
                    gid, kickoff, week=week + 1, location="Neutral", home_team=home, away_team=away
                )
            )
            labels.append(
                label(
                    gid,
                    kickoff,
                    home_score=24 + offense[home] + defense[away],
                    away_score=24 + offense[away] + defense[home],
                )
            )
        order = [order[0], order[-1], *order[1:-1]]
    return schedules, labels, offense, defense
