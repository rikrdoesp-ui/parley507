"""Esquema SQLite común. Dato faltante = NULL, nunca cero. Cada fila guarda su fuente."""
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from . import config

ESQUEMA = """
CREATE TABLE IF NOT EXISTS data_sources(
  source_id INTEGER PRIMARY KEY, provider TEXT NOT NULL, endpoint_or_dataset TEXT NOT NULL,
  source_url TEXT, license TEXT, captured_at TEXT NOT NULL, notes TEXT);
CREATE TABLE IF NOT EXISTS teams(
  team_id INTEGER PRIMARY KEY, abbreviation TEXT NOT NULL, full_name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS players(
  player_id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, name_key TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_players_key ON players(name_key);
CREATE TABLE IF NOT EXISTS games(
  game_id TEXT PRIMARY KEY, season TEXT NOT NULL, season_type TEXT NOT NULL, game_date TEXT NOT NULL,
  start_time_utc TEXT, home_team_id INTEGER, away_team_id INTEGER, venue TEXT, neutral_site INTEGER,
  status TEXT, home_score INTEGER, away_score INTEGER, overtime_periods INTEGER, source_id INTEGER);
CREATE TABLE IF NOT EXISTS nba_player_game_stats(
  game_id TEXT NOT NULL, player_id INTEGER NOT NULL, team_id INTEGER NOT NULL, season TEXT NOT NULL,
  game_date TEXT NOT NULL, minutes REAL, points INTEGER, rebounds INTEGER, offensive_rebounds INTEGER,
  defensive_rebounds INTEGER, assists INTEGER, steals INTEGER, blocks INTEGER, turnovers INTEGER,
  fgm INTEGER, fga INTEGER, fg3m INTEGER, fg3a INTEGER, ftm INTEGER, fta INTEGER, personal_fouls INTEGER,
  plus_minus INTEGER, starter INTEGER, source_id INTEGER NOT NULL, PRIMARY KEY(game_id, player_id));
CREATE INDEX IF NOT EXISTS ix_stats_player ON nba_player_game_stats(player_id, game_date);
-- Solo partidos con prórroga: estadísticas del tiempo reglamentario, para liquidar sin OT si Stake lo exige.
CREATE TABLE IF NOT EXISTS nba_player_game_stats_regulation(
  game_id TEXT NOT NULL, player_id INTEGER NOT NULL, minutes REAL, points INTEGER, rebounds INTEGER,
  assists INTEGER, fg3m INTEGER, steals INTEGER, blocks INTEGER, source_id INTEGER NOT NULL,
  PRIMARY KEY(game_id, player_id));
CREATE TABLE IF NOT EXISTS nba_injuries(
  injury_id INTEGER PRIMARY KEY, game_date TEXT NOT NULL, matchup TEXT, team_id INTEGER,
  player_name TEXT NOT NULL, player_id INTEGER, status TEXT NOT NULL, reason TEXT, reported_at TEXT,
  entry_method TEXT NOT NULL CHECK(entry_method IN ('PDF', 'MANUAL')), source_id INTEGER,
  captured_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS minutes_overrides(
  game_date TEXT NOT NULL, player_id INTEGER NOT NULL, minutes REAL NOT NULL, reason TEXT NOT NULL,
  entered_at TEXT NOT NULL, PRIMARY KEY(game_date, player_id));
-- Una sola tabla de props para todo deporte: un mercado nuevo es un valor de `market`, no una tabla.
CREATE TABLE IF NOT EXISTS player_props(
  prop_id INTEGER PRIMARY KEY, game_date TEXT NOT NULL, matchup TEXT, player_id INTEGER,
  player_name TEXT NOT NULL, market TEXT NOT NULL, line REAL NOT NULL, over_odds REAL, under_odds REAL,
  bookmaker TEXT NOT NULL, captured_at TEXT NOT NULL,
  entry_method TEXT NOT NULL CHECK(entry_method IN ('MANUAL', 'PARLEY_REF', 'API')), source_ref TEXT,
  UNIQUE(game_date, player_name, market, line, bookmaker, entry_method, source_ref));
CREATE TABLE IF NOT EXISTS predictions(
  prediction_id INTEGER PRIMARY KEY, game_id TEXT NOT NULL, game_date TEXT NOT NULL,
  player_id INTEGER NOT NULL, team_id INTEGER, market TEXT NOT NULL, scenario TEXT NOT NULL,
  minutes REAL, projected_mean REAL, dispersion REAL, lower_interval REAL, upper_interval REAL,
  sample_games INTEGER, minutes_sd REAL, model_version TEXT NOT NULL, generated_at TEXT NOT NULL,
  data_cutoff TEXT NOT NULL, notes TEXT);
CREATE INDEX IF NOT EXISTS ix_pred_fecha ON predictions(game_date, generated_at);
CREATE TABLE IF NOT EXISTS model_runs(
  run_id INTEGER PRIMARY KEY, sport TEXT NOT NULL, model_version TEXT NOT NULL, training_cutoff TEXT,
  params_json TEXT, metrics_json TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS data_quality_log(
  quality_id INTEGER PRIMARY KEY, table_name TEXT NOT NULL, record_id TEXT, check_name TEXT NOT NULL,
  severity TEXT NOT NULL, message TEXT NOT NULL, checked_at TEXT NOT NULL);
"""


def ahora_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clave_nombre(nombre: str) -> str:
    """Clave para unir nombres entre fuentes: sin tildes, mayúsculas ni signos (T.J. McConnell = tj mcconnell)."""
    plano = unicodedata.normalize("NFKD", str(nombre)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", plano)


def conectar(ruta: Path | None = None) -> sqlite3.Connection:
    ruta = ruta or config.DB
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(ESQUEMA)
    return con


def registrar_fuente(con: sqlite3.Connection, proveedor: str, endpoint: str, url: str = "", licencia: str = "",
                     notas: str = "") -> int:
    cur = con.execute("INSERT INTO data_sources(provider, endpoint_or_dataset, source_url, license, captured_at, notes)"
                      " VALUES (?, ?, ?, ?, ?, ?)", (proveedor, endpoint, url, licencia, ahora_utc(), notas))
    return cur.lastrowid


def calidad(con: sqlite3.Connection, tabla: str, registro: str, chequeo: str, severidad: str, mensaje: str) -> None:
    con.execute("INSERT INTO data_quality_log(table_name, record_id, check_name, severity, message, checked_at)"
                " VALUES (?, ?, ?, ?, ?, ?)", (tabla, registro, chequeo, severidad, mensaje, ahora_utc()))
