-- Relational staging schema (portable between SQLite and PostgreSQL).
-- Each source table is a "data product": loaded by one ingest module, mapped to RDF by R2RML.

CREATE TABLE IF NOT EXISTS gleif_entity (
    lei TEXT PRIMARY KEY,
    legal_name TEXT NOT NULL,
    legal_country TEXT,
    legal_jurisdiction TEXT,
    status TEXT,
    category TEXT
);

CREATE TABLE IF NOT EXISTS gleif_relationship (
    child_lei TEXT NOT NULL,
    parent_lei TEXT NOT NULL,
    rel_type TEXT NOT NULL,          -- DIRECT | ULTIMATE
    status TEXT,
    PRIMARY KEY (child_lei, parent_lei, rel_type)
);

CREATE TABLE IF NOT EXISTS cpv_code (
    code TEXT PRIMARY KEY,           -- 8 digits, no check digit
    label_en TEXT,
    label_de TEXT,
    parent_code TEXT
);

-- A "party" is an organisation as it appears in a procurement record (name + optional identifier).
CREATE TABLE IF NOT EXISTS party (
    party_id TEXT PRIMARY KEY,       -- 'P-' + hash; doubles as the entity key while unresolved
    source TEXT,
    scheme TEXT,                     -- identifier scheme as published (e.g. XI-LEI)
    identifier TEXT,
    name TEXT NOT NULL,
    country TEXT
);

CREATE TABLE IF NOT EXISTS tender (
    tender_id TEXT PRIMARY KEY,
    title TEXT,
    description TEXT,
    buyer_party_id TEXT,
    publication_date TEXT,
    source TEXT
);

CREATE TABLE IF NOT EXISTS award (
    award_id TEXT PRIMARY KEY,
    tender_id TEXT NOT NULL,
    supplier_party_id TEXT NOT NULL,
    value_amount NUMERIC,
    currency TEXT,
    award_date TEXT
);

CREATE TABLE IF NOT EXISTS tender_cpv (
    tender_id TEXT NOT NULL,
    cpv_code TEXT NOT NULL,
    source TEXT NOT NULL,            -- declared | linked
    score REAL,
    PRIMARY KEY (tender_id, cpv_code, source)
);

CREATE TABLE IF NOT EXISTS tender_requirement (
    tender_id TEXT NOT NULL,
    standard TEXT NOT NULL,
    span TEXT,
    method TEXT,
    PRIMARY KEY (tender_id, standard)
);

CREATE TABLE IF NOT EXISTS sanction_entry (
    entry_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    aliases TEXT,
    countries TEXT,
    dataset TEXT,
    schema_type TEXT
);

CREATE TABLE IF NOT EXISTS party_resolution (
    party_id TEXT PRIMARY KEY,
    lei TEXT,
    score REAL,
    method TEXT,
    status TEXT                      -- accepted | review | none
);

CREATE TABLE IF NOT EXISTS sanction_match (
    match_id TEXT PRIMARY KEY,
    entity_key TEXT NOT NULL,
    entry_id TEXT NOT NULL,
    score REAL NOT NULL,
    method TEXT NOT NULL,
    review_status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS regulation (
    reg_id TEXT PRIMARY KEY,
    title TEXT,
    celex TEXT,
    url TEXT
);

CREATE TABLE IF NOT EXISTS extraction_run (
    run_id TEXT PRIMARY KEY,
    started_at TEXT,
    model TEXT,
    method TEXT,
    prompt_hash TEXT
);

CREATE TABLE IF NOT EXISTS obligation (
    obl_id TEXT PRIMARY KEY,
    reg_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    article TEXT,
    text TEXT NOT NULL,
    applies_to_role TEXT,            -- buyer | supplier | both
    confidence REAL
);

CREATE TABLE IF NOT EXISTS kg_scope (
    lei TEXT PRIMARY KEY
);

-- ------------------------------ views used by the R2RML mapping --------------------------

CREATE VIEW v_resolution AS
SELECT p.party_id,
       p.name,
       p.country,
       CASE WHEN r.status = 'accepted' AND r.lei IS NOT NULL THEN r.lei ELSE p.party_id END AS entity_key,
       CASE WHEN r.status = 'accepted' AND r.lei IS NOT NULL THEN 1 ELSE 0 END AS resolved
FROM party p LEFT JOIN party_resolution r ON r.party_id = p.party_id;

CREATE VIEW v_entity_gleif AS
SELECT g.lei AS entity_key, g.legal_name AS legal_name, g.legal_country AS country, g.lei AS lei
FROM gleif_entity g
WHERE (SELECT COUNT(*) FROM kg_scope) = 0
   OR g.lei IN (SELECT lei FROM kg_scope)
   OR g.lei IN (SELECT lei FROM party_resolution WHERE status = 'accepted');

CREATE VIEW v_entity_party AS
SELECT p.party_id AS entity_key, p.name AS legal_name, p.country AS country, CAST(NULL AS TEXT) AS lei
FROM party p LEFT JOIN party_resolution r ON r.party_id = p.party_id
WHERE r.party_id IS NULL OR r.status <> 'accepted' OR r.lei IS NULL;

CREATE VIEW v_entity AS
SELECT entity_key, legal_name, country, lei FROM v_entity_gleif
UNION ALL
SELECT entity_key, legal_name, country, lei FROM v_entity_party;

CREATE VIEW v_alias AS
SELECT vr.entity_key AS entity_key, vr.name AS alias
FROM v_resolution vr WHERE vr.resolved = 1;

CREATE VIEW v_country AS
SELECT DISTINCT country AS code FROM v_entity WHERE country IS NOT NULL;

CREATE VIEW v_parent AS
SELECT rl.child_lei AS child_key, rl.parent_lei AS parent_key, rl.rel_type AS rel_type
FROM gleif_relationship rl
WHERE rl.child_lei IN (SELECT entity_key FROM v_entity_gleif)
  AND rl.parent_lei IN (SELECT entity_key FROM v_entity_gleif);

CREATE VIEW v_tender AS
SELECT t.tender_id, t.title, t.description, t.publication_date, vr.entity_key AS buyer_key
FROM tender t JOIN v_resolution vr ON vr.party_id = t.buyer_party_id;

CREATE VIEW v_award AS
SELECT a.award_id, a.tender_id, a.value_amount, a.currency, a.award_date, vr.entity_key AS supplier_key
FROM award a JOIN v_resolution vr ON vr.party_id = a.supplier_party_id;

CREATE VIEW v_sanction_match AS
SELECT m.match_id, m.entity_key, m.entry_id, m.score, m.method, m.review_status
FROM sanction_match m
WHERE m.entity_key IN (SELECT entity_key FROM v_entity)
  AND m.entry_id IN (SELECT entry_id FROM sanction_entry);
