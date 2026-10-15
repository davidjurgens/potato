"""
Tables in ``<task_dir>/engine.sqlite``.

The engine has its own file rather than sharing ``project.sqlite``: a study of
a million items writes millions of prediction and call rows, and a separate WAL
keeps that traffic off the annotation path and lets the file be backed up on
its own.

Migrations are append-only. A change to a table is a new migration, never an
edit to one that has shipped.
"""

from potato.persistence import Migration, register_migration

DATABASE = "engine"

CORE = Migration(
    name="engine_0001_core",
    database=DATABASE,
    sql="""
CREATE TABLE IF NOT EXISTS engine_item (
    item_id      TEXT PRIMARY KEY,
    content_hash TEXT,
    ingest_seq   INTEGER,
    stratum      TEXT,
    meta_json    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_engine_item_seq ON engine_item(ingest_seq);

CREATE TABLE IF NOT EXISTS source_version (
    version_id           TEXT PRIMARY KEY,
    source_id            TEXT NOT NULL,
    kind                 TEXT NOT NULL,
    model                TEXT,
    endpoint_type        TEXT,
    revision             TEXT,
    params_json          TEXT NOT NULL DEFAULT '{}',
    prompt_template_hash TEXT,
    code_version         TEXT,
    created_at           REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_source_version_source ON source_version(source_id);

CREATE TABLE IF NOT EXISTS run (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    kind              TEXT NOT NULL,
    source_version_id TEXT,
    config_hash       TEXT,
    status            TEXT NOT NULL,
    cursor_json       TEXT NOT NULL DEFAULT '{}',
    started_at        REAL NOT NULL,
    finished_at       REAL,
    error             TEXT
);

CREATE TABLE IF NOT EXISTS prediction (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id           TEXT NOT NULL,
    schema_name       TEXT NOT NULL,
    source_version_id TEXT NOT NULL,
    run_id            INTEGER,
    value_json        TEXT,
    status            TEXT NOT NULL,
    raw_conf          REAL,
    conf_json         TEXT,
    calibrated_conf   REAL,
    calibrator_id     TEXT,
    call_ids_json     TEXT NOT NULL DEFAULT '[]',
    reasoning         TEXT,
    created_at        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_prediction_current
    ON prediction(item_id, schema_name, source_version_id, id DESC);
CREATE INDEX IF NOT EXISTS ix_prediction_version_conf
    ON prediction(source_version_id, schema_name, calibrated_conf);
CREATE INDEX IF NOT EXISTS ix_prediction_run ON prediction(run_id);

-- The latest prediction per (item, schema, source version). Predictions are
-- never updated in place, so this view is the only notion of "current".
CREATE VIEW IF NOT EXISTS current_prediction AS
    SELECT p.* FROM prediction p
    WHERE p.id = (
        SELECT MAX(q.id) FROM prediction q
        WHERE q.item_id = p.item_id
          AND q.schema_name = p.schema_name
          AND q.source_version_id = p.source_version_id
    );

CREATE TABLE IF NOT EXISTS model_call (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            INTEGER,
    source_version_id TEXT NOT NULL,
    endpoint_type     TEXT,
    model             TEXT,
    revision          TEXT,
    prompt_hash       TEXT,
    input_hash        TEXT,
    response_hash     TEXT,
    sample_idx        INTEGER NOT NULL DEFAULT 0,
    started_at        REAL NOT NULL,
    latency_ms        REAL,
    input_tokens      INTEGER,
    output_tokens     INTEGER,
    cost_usd          REAL,
    estimated         INTEGER NOT NULL DEFAULT 1,
    cache_hit         INTEGER NOT NULL DEFAULT 0,
    redaction_json    TEXT,
    error             TEXT,
    payload_ref       TEXT
);
CREATE INDEX IF NOT EXISTS ix_model_call_run ON model_call(run_id);
CREATE INDEX IF NOT EXISTS ix_model_call_version ON model_call(source_version_id);

CREATE TABLE IF NOT EXISTS cache (
    key        TEXT PRIMARY KEY,
    value      BLOB NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sampling_design (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    seed        INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS human_request (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id             TEXT NOT NULL,
    schema_name         TEXT NOT NULL,
    purpose             TEXT NOT NULL,
    design_id           INTEGER REFERENCES sampling_design(id),
    inclusion_prob      REAL,
    split               TEXT NOT NULL DEFAULT 'none',
    visibility          TEXT NOT NULL DEFAULT 'blind',
    shown_prediction_id INTEGER,
    pool                TEXT NOT NULL DEFAULT 'team',
    eligible_group      TEXT,
    assigned_user       TEXT,
    status              TEXT NOT NULL DEFAULT 'open',
    contract_id         TEXT,
    priority            REAL NOT NULL DEFAULT 0,
    label_json          TEXT,
    user_id             TEXT,
    cost_usd            REAL,
    created_at          REAL NOT NULL,
    completed_at        REAL
);
CREATE INDEX IF NOT EXISTS ix_request_open
    ON human_request(status, pool, priority DESC, id);
CREATE INDEX IF NOT EXISTS ix_request_item ON human_request(item_id, schema_name);
CREATE INDEX IF NOT EXISTS ix_request_user ON human_request(assigned_user, status);

CREATE TABLE IF NOT EXISTS resolved_label (
    item_id             TEXT NOT NULL,
    schema_name         TEXT NOT NULL,
    value_json          TEXT,
    origin              TEXT NOT NULL,
    status              TEXT NOT NULL,
    source_version_id   TEXT,
    request_ids_json    TEXT NOT NULL DEFAULT '[]',
    contract_version_id INTEGER,
    certificate_id      INTEGER,
    updated_at          REAL NOT NULL,
    PRIMARY KEY (item_id, schema_name)
);
CREATE INDEX IF NOT EXISTS ix_resolved_status ON resolved_label(schema_name, status);

CREATE TABLE IF NOT EXISTS resolved_label_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id             TEXT NOT NULL,
    schema_name         TEXT NOT NULL,
    value_json          TEXT,
    origin              TEXT NOT NULL,
    status              TEXT NOT NULL,
    source_version_id   TEXT,
    request_ids_json    TEXT NOT NULL DEFAULT '[]',
    contract_version_id INTEGER,
    certificate_id      INTEGER,
    updated_at          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_resolved_history_item
    ON resolved_label_history(item_id, schema_name, id);

CREATE TABLE IF NOT EXISTS contract_version (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id  TEXT NOT NULL,
    kind         TEXT NOT NULL,
    params_json  TEXT NOT NULL DEFAULT '{}',
    cascade_hash TEXT NOT NULL,
    looks        INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL,
    result_json  TEXT NOT NULL DEFAULT '{}',
    created_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_contract_version ON contract_version(contract_id, id DESC);

CREATE TABLE IF NOT EXISTS certificate (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    cascade_hash              TEXT NOT NULL,
    dataset_hash              TEXT NOT NULL,
    contract_version_ids_json TEXT NOT NULL DEFAULT '[]',
    sections_json             TEXT NOT NULL DEFAULT '{}',
    budget_json               TEXT NOT NULL DEFAULT '{}',
    content_sha256            TEXT NOT NULL,
    created_at                REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS budget (
    kind      TEXT NOT NULL,
    scope     TEXT NOT NULL DEFAULT 'study',
    limit_val REAL,
    spent     REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (kind, scope)
);

-- One row per process that may write runs, so a CLI run and a live server do
-- not both drive the same study.
CREATE TABLE IF NOT EXISTS writer_lock (
    name        TEXT PRIMARY KEY,
    holder      TEXT NOT NULL,
    acquired_at REAL NOT NULL,
    heartbeat   REAL NOT NULL
);
""",
)

#: When a request was handed to a person, so a stale hold can be released.
ASSIGNED_AT = Migration(
    name="engine_0002_assigned_at",
    database=DATABASE,
    sql="ALTER TABLE human_request ADD COLUMN assigned_at REAL;",
)

#: Small engine state that is not a record of its own: distilled models.
KV = Migration(
    name="engine_0003_kv",
    database=DATABASE,
    sql="""CREATE TABLE IF NOT EXISTS engine_kv (
        key        TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        updated_at REAL NOT NULL
    );""",
)

MIGRATIONS = (CORE, ASSIGNED_AT, KV)
for _m in MIGRATIONS:
    register_migration(_m)
