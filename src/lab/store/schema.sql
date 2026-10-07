-- Core tables. Snapshots and forecasts are append-only; nothing is updated in place.

CREATE TABLE IF NOT EXISTS market_snapshot (
    venue          VARCHAR NOT NULL,
    market_ticker  VARCHAR NOT NULL,
    event_ticker   VARCHAR,
    ts_utc         TIMESTAMP NOT NULL,
    yes_bid        DOUBLE, yes_ask DOUBLE, no_bid DOUBLE, no_ask DOUBLE,
    last           DOUBLE,
    volume         DOUBLE,
    open_interest  DOUBLE
);

CREATE TABLE IF NOT EXISTS contract (
    venue          VARCHAR NOT NULL,
    market_ticker  VARCHAR NOT NULL,
    event_ticker   VARCHAR,
    series         VARCHAR,
    kind           VARCHAR CHECK (kind IN ('threshold', 'bracket', 'winner', 'spread')),
    strike_low     DOUBLE,
    strike_high    DOUBLE,
    close_ts       TIMESTAMP,
    settle_ts      TIMESTAMP,
    result         VARCHAR,
    PRIMARY KEY (venue, market_ticker)
);

CREATE TABLE IF NOT EXISTS fee_schedule (
    venue       VARCHAR NOT NULL,
    series      VARCHAR NOT NULL,
    fee_type    VARCHAR NOT NULL,
    multiplier  DOUBLE NOT NULL,
    valid_from  TIMESTAMP NOT NULL,
    PRIMARY KEY (venue, series, valid_from)
);

CREATE TABLE IF NOT EXISTS econ_vintage (
    series_id       VARCHAR NOT NULL,
    ref_period      DATE NOT NULL,
    value           DOUBLE,
    realtime_start  DATE NOT NULL,
    realtime_end    DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS nowcast_snapshot (
    idx         VARCHAR NOT NULL,
    ref_period  VARCHAR NOT NULL,
    value       DOUBLE,
    fetched_ts  TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS nfl_game (
    game_id VARCHAR PRIMARY KEY, season INTEGER, week INTEGER, game_type VARCHAR,
    kickoff_ts TIMESTAMP, away_team VARCHAR, home_team VARCHAR,
    away_score INTEGER, home_score INTEGER
);
-- 'Home' or 'Neutral' (nflverse `location`); neutral-site games get no home-field adjustment.
ALTER TABLE nfl_game ADD COLUMN IF NOT EXISTS location VARCHAR;

CREATE TABLE IF NOT EXISTS nfl_injury (
    game_id VARCHAR, team VARCHAR, player VARCHAR, status VARCHAR, fetched_ts TIMESTAMP NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS forecast_id_seq;
CREATE TABLE IF NOT EXISTS forecast (
    forecast_id    BIGINT PRIMARY KEY DEFAULT nextval('forecast_id_seq'),
    model          VARCHAR NOT NULL,
    model_version  VARCHAR NOT NULL,
    git_sha        VARCHAR NOT NULL,
    venue          VARCHAR NOT NULL,
    market_ticker  VARCHAR NOT NULL,
    as_of_ts       TIMESTAMP NOT NULL,
    p_yes          DOUBLE NOT NULL CHECK (p_yes >= 0 AND p_yes <= 1),
    created_ts     TIMESTAMP NOT NULL,
    -- a forecast cannot be created after the information cutoff it claims
    CHECK (created_ts >= as_of_ts)
);

CREATE TABLE IF NOT EXISTS paper_trade (
    forecast_id  BIGINT NOT NULL,
    side         VARCHAR NOT NULL CHECK (side IN ('yes', 'no')),
    qty          INTEGER NOT NULL,
    price        DOUBLE NOT NULL,
    fee          DOUBLE NOT NULL,
    decision_ts  TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS settlement (
    venue VARCHAR NOT NULL, market_ticker VARCHAR NOT NULL,
    result VARCHAR NOT NULL, settled_ts TIMESTAMP NOT NULL,
    PRIMARY KEY (venue, market_ticker)
);
