"""Local-only RF-001 observations, version selection and fail-closed input gate.

No ingest/config imports: this module never downloads data or loads dotenv.
"""

from __future__ import annotations

import csv
import hashlib
import io
import itertools
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

ALIASES = {"OAK": "LV", "SD": "LAC", "STL": "LA"}
ALIAS_VERSION = "franchise-v1"
COHORTS = {"strict_pit", "reconstructed_scores"}
FINISH_LAG = timedelta(hours=4)
REQUIRED = {
    "schedules": {
        "game_id",
        "season",
        "week",
        "game_type",
        "kickoff_ts_utc",
        "home_team",
        "away_team",
        "location",
        "revision_id",
    },
    "labels": {"game_id", "season", "home_score", "away_score", "completed", "revision_id"},
}


def required_headers(headers, kind):
    missing = REQUIRED[kind] - set(headers)
    if missing:
        raise ValueError(f"required {kind} fields/headers missing: {sorted(missing)}")


def completed(value):
    if type(value) is bool:
        return value
    if type(value) is int and value in (0, 1):
        return bool(value)
    if type(value) is str and value in {"true", "True", "1", "false", "False", "0"}:
        return value in {"true", "True", "1"}
    raise ValueError("invalid completed value; exact boolean encoding required")


def utc(value) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return result.astimezone(UTC)


def stamp(value: datetime) -> str:
    return utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical(value) -> str:
    def encode(x):
        if isinstance(x, datetime):
            return stamp(x)
        if hasattr(x, "__dataclass_fields__"):
            return asdict(x)
        raise TypeError(type(x).__name__)

    return json.dumps(value, default=encode, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def optional_time(value):
    return None if value is None or value == "" else utc(value)


def integer(value, name):
    number = float(value)
    if not number.is_integer() or number < 0:
        raise ValueError(f"invalid {name}")
    return int(number)


@dataclass(frozen=True)
class Vintage:
    revision_id: str
    published_ts: datetime | None
    first_seen_ts: datetime | None
    fetched_ts: datetime | None
    source_hash: str
    availability_evidence: str
    evidence_ref: str

    @classmethod
    def from_row(cls, row):
        revision = str(row.get("revision_id", ""))
        if not revision:
            raise ValueError("revision_id required")
        return cls(
            revision,
            optional_time(row.get("published_ts")),
            optional_time(row.get("first_seen_ts")),
            optional_time(row.get("fetched_ts")),
            str(row.get("source_hash", "")),
            str(row.get("availability_evidence", "")),
            str(row.get("evidence_ref", "")),
        )

    def available(self, as_of):
        valid_hash = len(self.source_hash) == 64 and all(
            c in "0123456789abcdef" for c in self.source_hash
        )
        if not valid_hash or not self.evidence_ref:
            return False
        if self.availability_evidence == "contemporaneous_receipt":
            # A receipt proves presence only when we actually received it.
            times = [t for t in (self.first_seen_ts, self.fetched_ts) if t is not None]
            return (
                bool(times)
                and min(times) < as_of
                and (self.published_ts is None or self.published_ts < as_of)
            )
        if self.availability_evidence == "timestamped_public_archive":
            return self.published_ts is not None and self.published_ts < as_of
        return False

    def order(self, clock="published_ts"):
        return getattr(self, clock) or datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Game:
    game_id: str
    season: int
    week: int
    game_type: str
    kickoff: datetime
    home_team: str
    away_team: str
    location: str
    vintage: Vintage

    @property
    def as_of(self):
        return self.kickoff - timedelta(hours=24)


@dataclass(frozen=True)
class Label:
    game_id: str
    season: int
    home_score: int | None
    away_score: int | None
    completed: bool
    vintage: Vintage

    @property
    def revision_id(self):
        return self.vintage.revision_id


@dataclass(frozen=True)
class Observation:
    game: Game
    label: Label


@dataclass(frozen=True)
class UnavailableSchedule:
    game_id: str
    season: int
    vintage: Vintage
    reason: str
    week: int
    game_type: str
    location: str


class Dataset:
    def __init__(self, games, labels, cohort, exclusions, revision_clock):
        self.revision_clock = revision_clock
        self.games = tuple(
            sorted(games, key=lambda g: (g.kickoff, g.game_id, g.vintage.order(revision_clock)))
        )
        self.labels = tuple(
            sorted(labels, key=lambda x: (x.game_id, x.vintage.order(revision_clock)))
        )
        self.cohort = cohort
        self.unavailable_schedules = tuple(UnavailableSchedule(**x) for x in exclusions)
        valid_ids = {g.game_id for g in self.targets()}
        self.exclusions = sorted(
            {
                x["game_id"]: {k: v for k, v in x.items() if k != "vintage"}
                for x in sorted(exclusions, key=lambda x: x["vintage"].order(revision_clock))
                if x["game_id"] not in valid_ids
            }.values(),
            key=lambda x: x["game_id"],
        )

    @classmethod
    def from_rows(cls, schedules, labels, cohort, *, revision_clock=None):
        if cohort not in COHORTS:
            raise ValueError("unsupported cohort")
        revision_clock = revision_clock or (
            "published_ts" if cohort == "strict_pit" else "fetched_ts"
        )
        if revision_clock not in {"published_ts", "first_seen_ts", "fetched_ts"}:
            raise ValueError("invalid revision order clock")
        games, parsed_labels, exclusions = [], [], []
        keys, seasons, identities = set(), {}, {}
        for row in schedules:
            required_headers(row, "schedules")
            if "home_score" in row or "away_score" in row:
                raise ValueError("score-bearing schedule is forbidden")
            gid = str(row.get("game_id", ""))
            if not gid:
                raise ValueError("game_id required")
            season = integer(row["season"], "season")
            if not 1999 <= season <= 2023:
                raise ValueError("unapproved season / locked holdout")
            vintage = Vintage.from_row(row)
            key = (gid, vintage.revision_id)
            if key in keys:
                raise ValueError("duplicate schedule revision")
            keys.add(key)
            if gid in seasons and seasons[gid] != season:
                raise ValueError("ambiguous game season")
            seasons[gid] = season
            week = integer(row["week"], "week")
            game_type = row["game_type"]
            if game_type not in {"REG", "POST", "WC", "DIV", "CON", "SB"}:
                raise ValueError("unsupported game_type (preseason excluded upstream)")
            if row["location"] not in {"Home", "Neutral"}:
                raise ValueError("unknown location")
            metadata = {"week": week, "game_type": game_type, "location": row["location"]}
            if not row.get("kickoff_ts_utc"):
                exclusions.append(
                    {
                        "game_id": gid,
                        "season": season,
                        "reason": "missing_kickoff",
                        "vintage": vintage,
                        **metadata,
                    }
                )
                continue
            if not row.get("home_team") or not row.get("away_team"):
                exclusions.append(
                    {
                        "game_id": gid,
                        "season": season,
                        "reason": "missing_team",
                        "vintage": vintage,
                        **metadata,
                    }
                )
                continue
            home = ALIASES.get(row["home_team"], row["home_team"])
            away = ALIASES.get(row["away_team"], row["away_team"])
            if home == away:
                raise ValueError("alias join produces same team")
            if gid in identities and identities[gid] != (home, away):
                raise ValueError("ambiguous schedule identity between revisions")
            identities[gid] = (home, away)
            games.append(
                Game(
                    gid,
                    season,
                    week,
                    game_type,
                    utc(row["kickoff_ts_utc"]),
                    home,
                    away,
                    row["location"],
                    vintage,
                )
            )
        keys, times = set(), set()
        for row in labels:
            required_headers(row, "labels")
            gid, season = str(row["game_id"]), integer(row["season"], "season")
            if not 1999 <= season <= 2023:
                raise ValueError("unapproved label season / locked holdout")
            if gid not in seasons or seasons[gid] != season:
                raise ValueError("label without matching schedule season")
            vintage = Vintage.from_row(row)
            if (gid, vintage.revision_id) in keys:
                raise ValueError("duplicate label revision")
            keys.add((gid, vintage.revision_id))
            time_key = (gid, vintage.order(revision_clock))
            if time_key in times:
                raise ValueError("ambiguous same-time label revisions")
            times.add(time_key)
            hs, aws = row.get("home_score"), row.get("away_score")
            complete = completed(row["completed"])
            parsed_labels.append(
                Label(
                    gid,
                    season,
                    None if hs is None or hs == "" else integer(hs, "home_score"),
                    None if aws is None or aws == "" else integer(aws, "away_score"),
                    complete,
                    vintage,
                )
            )
        versions = {}
        for game in [*games, *(UnavailableSchedule(**x) for x in exclusions)]:
            versions.setdefault(game.game_id, []).append(game.vintage)
        for vintages in versions.values():
            if len(vintages) > 1:
                if any(getattr(v, revision_clock) is None for v in vintages):
                    raise ValueError(
                        "multiple schedule revisions require the declared revision clock"
                    )
                if len({v.order(revision_clock) for v in vintages}) != len(vintages):
                    raise ValueError("ambiguous same-time schedule revisions")
        label_versions = {}
        for x in parsed_labels:
            label_versions.setdefault(x.game_id, []).append(x.vintage)
        if any(
            len(vs) > 1 and any(getattr(v, revision_clock) is None for v in vs)
            for vs in label_versions.values()
        ):
            raise ValueError("multiple label revisions require the declared revision clock")
        physical = {}
        for game in games:
            key = (game.season, game.home_team, game.away_team, game.kickoff)
            if key in physical and physical[key] != game.game_id:
                raise ValueError("duplicate physical game under different IDs")
            physical[key] = game.game_id
        latest = {}
        for game in sorted(games, key=lambda g: g.vintage.order(revision_clock)):
            latest[game.game_id] = game
        by_team = {}
        for game in latest.values():
            for team in (game.home_team, game.away_team):
                by_team.setdefault(team, []).append(game)
        for team_games in by_team.values():
            ordered = sorted(team_games, key=lambda g: g.kickoff)
            if any(b.kickoff - a.kickoff < FINISH_LAG for a, b in itertools.pairwise(ordered)):
                raise ValueError("overlapping team games under different IDs")
        return cls(games, parsed_labels, cohort, exclusions, revision_clock)

    def schedules_at(self, as_of):
        latest = {}
        for game in (*self.games, *self.unavailable_schedules):
            if self.cohort == "strict_pit" and not game.vintage.available(as_of):
                continue
            if game.game_id not in latest or (
                game.vintage.order(self.revision_clock)
                > latest[game.game_id].vintage.order(self.revision_clock)
            ):
                latest[game.game_id] = game
        return latest

    def targets(self):
        latest = {}
        for game in self.games:
            if self.cohort == "strict_pit" and not game.vintage.available(game.as_of):
                continue
            at_cutoff = self.schedules_at(game.as_of).get(game.game_id)
            if at_cutoff == game:
                latest[game.game_id] = game
        return sorted(latest.values(), key=lambda g: (g.kickoff, g.game_id))

    def eligible(self, as_of):
        as_of = utc(as_of)
        games, latest = self.schedules_at(as_of), {}
        for label in self.labels:
            game = games.get(label.game_id)
            if not isinstance(game, Game) or not game.kickoff + FINISH_LAG < as_of:
                continue
            if self.cohort == "strict_pit" and not label.vintage.available(as_of):
                continue
            # Reconstructed versions are explicitly hindsight final-data assumptions.
            if label.game_id not in latest or (
                label.vintage.order(self.revision_clock)
                > latest[label.game_id].label.vintage.order(self.revision_clock)
            ):
                latest[label.game_id] = Observation(game, label)
        return sorted(
            (
                o
                for o in latest.values()
                if o.label.completed
                and o.label.home_score is not None
                and o.label.away_score is not None
            ),
            key=lambda o: (o.game.kickoff, o.game.game_id),
        )

    def evaluation_label(self, game_id):
        labels = [x for x in self.labels if x.game_id == game_id]
        latest = max(labels, key=lambda x: x.vintage.order(self.revision_clock)) if labels else None
        return (
            latest
            if (
                latest
                and latest.completed
                and latest.home_score is not None
                and latest.away_score is not None
            )
            else None
        )


DEVELOPMENT_SEASONS = tuple(range(2006, 2024))
EXECUTION_POLICY_ID = "rf001-reconstructed-2006-2023-v1"
POPULATION_FIELDS = ("documented_scheduled", "retained_completed", "externally_excluded")


def source_url(value):
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return parsed.scheme == "https" and bool(parsed.netloc) and not any(c.isspace() for c in value)


def validate_execution_policy(manifest, *, required=False):
    """Validate declared execution scope before reading any game artifacts.

    Read-only legacy archive loading need not adopt an execution policy. A real
    RF-001 run requires the exact registered contract. Evidence URLs/flags remain
    human-reviewed assertions, not documents authenticated by this offline code.
    Synthetic runs without policy remain compatible; explicit synthetic policies
    exercise accounting on smaller invented populations.
    """
    policy = manifest.get("execution_policy")
    real = not manifest["synthetic"]
    if policy is None:
        if real and required:
            raise ValueError("real execution policy required before game inputs")
        return
    fixed = {
        "schema_version": 1,
        "policy_id": EXECUTION_POLICY_ID,
        "baseline_replay_start": 2006,
        "candidate_fit_start": 2006,
        "baseline_extra_history": "none",
        "cancellation_policy": "exclude_no_contest_from_completed_game_cohort",
    }
    if (
        not isinstance(policy, dict)
        or any(policy.get(k) != v for k, v in fixed.items())
        or type(policy.get("schema_version")) is not int
        or type(policy.get("baseline_replay_start")) is not int
        or type(policy.get("candidate_fit_start")) is not int
        or manifest["cohort"] != "reconstructed_scores"
    ):
        raise ValueError("unsupported reconstructed execution policy/start/history")
    years = policy.get("input_seasons")
    if (
        not isinstance(years, list)
        or not years
        or any(type(y) is not int or y not in DEVELOPMENT_SEASONS for y in years)
        or years != sorted(set(years))
        or (real and years != list(DEVELOPMENT_SEASONS))
    ):
        raise ValueError("execution policy requires the fixed 2006–2023 season contract")
    declared = Counter((p["season"], p["kind"]) for p in manifest["partitions"])
    expected = Counter((y, k) for y in years for k in ("schedules", "labels"))
    if declared != expected:
        raise ValueError(
            "execution policy requires one partition per season/kind, with no extra history"
        )
    accounting = policy.get("population_accounting", {})
    per_year = accounting.get("per_season", {})
    if not isinstance(per_year, dict) or set(per_year) != {str(y) for y in years}:
        raise ValueError("population accounting needs every declared season")
    for block in [accounting, *per_year.values()]:
        if (
            not isinstance(block, dict)
            or any(type(block.get(k)) is not int or block[k] < 0 for k in POPULATION_FIELDS)
            or block["documented_scheduled"]
            != block["retained_completed"] + block["externally_excluded"]
        ):
            raise ValueError("population scheduled/completed/excluded counts do not reconcile")
    if any(
        accounting[k] != sum(block[k] for block in per_year.values()) for k in POPULATION_FIELDS
    ):
        raise ValueError("population totals do not equal season counts")
    exclusions = policy.get("external_population_exclusions")
    required_keys = {
        "game_id",
        "season",
        "week",
        "game_type",
        "home_team",
        "away_team",
        "reason",
        "source_row_present",
        "audit_ref",
    }
    if not isinstance(exclusions, list) or len(exclusions) != accounting["externally_excluded"]:
        raise ValueError("external population exclusions must be a list with the registered count")
    ids = set()
    for row in exclusions:
        if (
            not isinstance(row, dict)
            or not required_keys <= row.keys()
            or type(row["season"]) is not int
            or row["season"] not in years
            or type(row["week"]) is not int
            or row["week"] < 1
            or not isinstance(row["game_id"], str)
            or not row["game_id"]
            or row["game_id"] in ids
            or row["game_type"] != "REG"
            or row["reason"] != "cancelled_no_contest"
            or row["source_row_present"] is not False
            or not row["home_team"]
            or not row["away_team"]
            or row["home_team"] == row["away_team"]
            or not source_url(row["audit_ref"])
            or {"kickoff", "kickoff_ts_utc", "as_of", "location", "home_score", "away_score"}
            & row.keys()
        ):
            raise ValueError("invalid external cancellation population record")
        ids.add(row["game_id"])
    by_year = Counter(r["season"] for r in exclusions)
    if any(per_year[str(y)]["externally_excluded"] != by_year[y] for y in years):
        raise ValueError("external population ledger does not reconcile by season")
    if real:
        for year in years:
            scheduled = 267 if year < 2020 else 269 if year == 2020 else 285
            excluded = int(year == 2022)
            if per_year[str(year)] != {
                "documented_scheduled": scheduled,
                "retained_completed": scheduled - excluded,
                "externally_excluded": excluded,
            }:
                raise ValueError("real population differs from the registered season counts")
        if len(exclusions) != 1 or any(
            exclusions[0][k] != v
            for k, v in {
                "game_id": "2022_17_BUF_CIN",
                "season": 2022,
                "week": 17,
                "home_team": "CIN",
                "away_team": "BUF",
            }.items()
        ):
            raise ValueError("real cancellation must be the registered 2022 BUF/CIN no-contest")
        rules = manifest.get("postseason_rule_metadata", {})
        for year in years:
            rule = rules.get(str(year))
            if (
                not isinstance(rule, dict)
                or type(rule.get("season")) is not int
                or rule["season"] != year
                or rule.get("reviewed") is not True
                or rule.get("no_final_ties") is not True
                or not isinstance(rule.get("sources"), list)
                or not rule["sources"]
                or not all(source_url(url) for url in rule["sources"])
            ):
                raise ValueError(
                    "real postseason needs reviewed season-specific structured rule metadata"
                )


def validate_population(dataset, manifest):
    """Reconcile loaded identities/final completion with policy, without fitting."""
    policy = manifest.get("execution_policy")
    if policy is None:
        return
    validate_execution_policy(manifest)
    external = {r["game_id"] for r in policy["external_population_exclusions"]}
    all_schedules = [*dataset.games, *dataset.unavailable_schedules]
    schedules = {r.game_id: r.season for r in all_schedules}
    labels = {r.game_id: r.season for r in dataset.labels}
    if external & (schedules.keys() | labels.keys()):
        raise ValueError("external population exclusion overlaps schedule/label inputs")
    completed = {gid for gid in labels if dataset.evaluation_label(gid) is not None}
    if schedules.keys() != labels.keys() or schedules.keys() != completed:
        raise ValueError("retained population requires matching schedules and completed labels")
    years = policy["input_seasons"]
    if set(schedules.values()) - set(years) or set(labels.values()) - set(years):
        raise ValueError("actual population includes unregistered seasons")
    for year in years:
        actual = sum(season == year for season in schedules.values())
        if actual != policy["population_accounting"]["per_season"][str(year)]["retained_completed"]:
            raise ValueError("actual completed population does not reconcile by season")


def load_manifest(path: Path, *, require_execution_policy=False):
    """Validate ALL partition declarations before reading ANY game artifact.

    Audited single-season metadata is a trust boundary: hashes pin content, not
    the truth of a declaration. Mislabelled files cannot be identified unread.
    """
    path = Path(path)
    if path.is_symlink() or path.suffix != ".json" or ".env" in path.resolve().parts:
        raise ValueError("unsafe manifest path")
    manifest = json.loads(path.read_text())
    if manifest.get("schema_version") != 1 or manifest.get("cohort") not in COHORTS:
        raise ValueError("unsupported manifest schema/cohort")
    if type(manifest.get("synthetic")) is not bool:
        raise ValueError("explicit synthetic flag required")
    partitions = manifest["partitions"]
    paths = set()
    for part in partitions:
        if "seasons" in part:
            raise ValueError("mixed-season artifacts forbidden")
        season = part["season"]
        if type(season) is not int or not 1999 <= season <= 2023:
            raise ValueError("unapproved season / locked holdout")
        required_role = "baseline_warmup" if season < 2006 else "development"
        if part["role"] != required_role or part["kind"] not in {"schedules", "labels"}:
            raise ValueError("unapproved partition role/kind")
        relative = Path(part["path"])
        if (
            relative.is_absolute()
            or any(p.startswith(".") for p in relative.parts)
            or relative.suffix not in {".csv", ".parquet"}
        ):
            raise ValueError("unsafe artifact path")
        resolved = (path.parent / relative).resolve()
        symlink = any(
            (path.parent / Path(*relative.parts[:i])).is_symlink()
            for i in range(1, len(relative.parts) + 1)
        )
        if (
            symlink
            or not resolved.is_relative_to(path.parent.resolve())
            or resolved in paths
            or ".env" in resolved.parts
        ):
            raise ValueError("unsafe/duplicate artifact path")
        paths.add(resolved)
        if len(part.get("sha256", "")) != 64:
            raise ValueError("pinned artifact hash required")
        if not manifest["synthetic"] and not part.get("audit", {}).get("season_isolated"):
            raise ValueError("real inputs require pre-read season isolation audit")
    validate_execution_policy(manifest, required=require_execution_policy)
    rows = {"schedules": [], "labels": []}
    for part in sorted(partitions, key=lambda p: (p["season"], p["kind"], p["path"])):
        artifact = path.parent / part["path"]
        raw = artifact.read_bytes()
        raw_hash = hashlib.sha256(raw).hexdigest()
        if raw_hash != part["sha256"]:
            raise ValueError("artifact hash mismatch")
        if artifact.suffix == ".csv":
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
            required_headers(reader.fieldnames or [], part["kind"])
            records = list(reader)
        else:
            import polars as pl

            frame = pl.read_parquet(io.BytesIO(raw))
            required_headers(frame.columns, part["kind"])
            records = frame.to_dicts()
        if manifest["synthetic"] and any(
            not str(r.get("evidence_ref", "")).startswith("synthetic://") for r in records
        ):
            raise ValueError("synthetic inputs require synthetic:// evidence markers")
        if any(integer(r["season"], "season") != part["season"] for r in records):
            raise ValueError("partition season disagrees with audited metadata")
        rows[part["kind"]].extend(records)
    dataset = Dataset.from_rows(
        rows["schedules"],
        rows["labels"],
        manifest["cohort"],
        revision_clock=manifest.get("revision_clock"),
    )
    validate_population(dataset, manifest)
    return dataset, manifest
