PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    spec TEXT,
    unit TEXT NOT NULL DEFAULT '件',
    category TEXT,
    aliases TEXT,
    shelf_life_days INTEGER,
    min_remaining_ratio REAL NOT NULL DEFAULT 0.66
);

CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    tier TEXT NOT NULL DEFAULT 'B',
    blacklisted INTEGER NOT NULL DEFAULT 0,
    delivery_rate REAL NOT NULL DEFAULT 0.95
);

CREATE TABLE IF NOT EXISTS supplier_qualifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id INTEGER NOT NULL REFERENCES suppliers (id) ON DELETE CASCADE,
    qual_type TEXT NOT NULL,
    issued_at DATE NOT NULL,
    expires_at DATE NOT NULL,
    material_id INTEGER REFERENCES materials (id),
    scope TEXT
);

CREATE TABLE IF NOT EXISTS quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id INTEGER NOT NULL REFERENCES suppliers (id),
    material_id INTEGER NOT NULL REFERENCES materials (id),
    unit_price REAL NOT NULL,
    freight REAL NOT NULL DEFAULT 0,
    lead_days INTEGER NOT NULL,
    valid_until DATE NOT NULL,
    available INTEGER NOT NULL DEFAULT 1,
    min_order_qty INTEGER NOT NULL DEFAULT 1,
    remaining_shelf_life_days INTEGER
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id INTEGER NOT NULL REFERENCES suppliers (id),
    material_id INTEGER NOT NULL REFERENCES materials (id),
    unit_price REAL NOT NULL,
    ordered_at DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_text TEXT NOT NULL,
    material_sku TEXT,
    quantity INTEGER,
    cost_center TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    request_text TEXT NOT NULL,
    state TEXT NOT NULL,
    structured_request TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    human_interventions INTEGER NOT NULL DEFAULT 0,
    token_usage TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    agent TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE (task_id, seq)
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    supplier_id INTEGER NOT NULL REFERENCES suppliers (id),
    material_id INTEGER NOT NULL REFERENCES materials (id),
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    total_amount REAL NOT NULL,
    lead_days INTEGER NOT NULL,
    cost_center TEXT,
    status TEXT NOT NULL DEFAULT 'CREATED',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    order_id INTEGER,
    decision TEXT NOT NULL,
    operator TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    matched_rules TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (scope, key)
);

CREATE TABLE IF NOT EXISTS fault_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flag TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events (task_id, seq);
CREATE INDEX IF NOT EXISTS idx_quotes_material ON quotes (material_id);
CREATE INDEX IF NOT EXISTS idx_price_history_material ON price_history (material_id, supplier_id);
