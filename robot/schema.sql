-- PrețBun database (SQLite locally, Cloudflare D1 in production). Spec §5.
-- Money: INTEGER bani. Dates: INTEGER days since 2026-01-01. Price tables: change-only, WITHOUT ROWID, no secondary indexes.

-- reference data (small)
CREATE TABLE IF NOT EXISTS chains   (id INTEGER PRIMARY KEY, name TEXT NOT NULL, source_key TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS zones    (id INTEGER PRIMARY KEY, chain_id INTEGER NOT NULL, name TEXT NOT NULL UNIQUE, rep_store_id INTEGER);
CREATE TABLE IF NOT EXISTS stores   (id INTEGER PRIMARY KEY, chain_id INTEGER NOT NULL, zone_id INTEGER NOT NULL,
                                     name TEXT NOT NULL, address TEXT, lat REAL NOT NULL, lon REAL NOT NULL,
                                     type INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS brands   (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS items    (id INTEGER PRIMARY KEY, name TEXT NOT NULL, unit TEXT);
CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY, name TEXT NOT NULL, parent_id INTEGER);
CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, name TEXT NOT NULL, title TEXT,
                                     brand_id INTEGER, item_id INTEGER, category_id INTEGER,
                                     size_qty INTEGER, size_unit TEXT, barcode TEXT);

-- prices with history: one row per change
CREATE TABLE IF NOT EXISTS zone_prices  (zone_id INTEGER NOT NULL, product_id INTEGER NOT NULL, day INTEGER NOT NULL,
                                         price INTEGER, promo INTEGER NOT NULL DEFAULT 0,
                                         PRIMARY KEY (zone_id, product_id, day)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS store_prices (store_id INTEGER NOT NULL, product_id INTEGER NOT NULL, day INTEGER NOT NULL,
                                         price INTEGER, promo INTEGER NOT NULL DEFAULT 0,
                                         PRIMARY KEY (store_id, product_id, day)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS zone_checks  (zone_id INTEGER NOT NULL, day INTEGER NOT NULL, products INTEGER NOT NULL,
                                         PRIMARY KEY (zone_id, day)) WITHOUT ROWID;

-- people (used from step 3)
CREATE TABLE IF NOT EXISTS users        (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, settings TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS areas        (id INTEGER PRIMARY KEY, name TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL, radius_m INTEGER NOT NULL DEFAULT 5000);
CREATE TABLE IF NOT EXISTS favorites    (user_id INTEGER NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('p','i')), ref INTEGER NOT NULL, day INTEGER NOT NULL,
                                         PRIMARY KEY (user_id, kind, ref)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS my_prices    (user_id INTEGER NOT NULL, store_id INTEGER NOT NULL, product_id INTEGER NOT NULL, day INTEGER NOT NULL,
                                         price INTEGER NOT NULL, PRIMARY KEY (user_id, store_id, product_id, day)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS lists        (user_id INTEGER PRIMARY KEY, data TEXT NOT NULL, updated INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS list_history (user_id INTEGER NOT NULL, day INTEGER NOT NULL, data TEXT NOT NULL,
                                         PRIMARY KEY (user_id, day)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS ratings      (product_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                                         stars INTEGER NOT NULL CHECK (stars BETWEEN 1 AND 5), day INTEGER NOT NULL,
                                         bought INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (product_id, user_id)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS rating_totals(product_id INTEGER PRIMARY KEY, n INTEGER NOT NULL, sum INTEGER NOT NULL);

-- catalog (step 2): new tables rather than new columns, so the live D1 needs no migration
CREATE TABLE IF NOT EXISTS item_info    (item_id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, shelf TEXT NOT NULL,
                                         size INTEGER, typical TEXT);
CREATE TABLE IF NOT EXISTS product_info (product_id INTEGER PRIMARY KEY, attrs TEXT);
CREATE TABLE IF NOT EXISTS facts        (product_id INTEGER PRIMARY KEY, code TEXT NOT NULL, grade TEXT, nova INTEGER,
                                         n TEXT, diet TEXT, allergens TEXT, image TEXT, day INTEGER NOT NULL);

-- price channels (spec 2026-11-09): online shops, app storefronts and stores with receipt prices; every non-official
-- price, change-only, with its source and day. Official in-store prices stay in zone_prices / store_prices.
CREATE TABLE IF NOT EXISTS places (id INTEGER PRIMARY KEY,
                                   channel TEXT NOT NULL CHECK (channel IN ('store','online','app')),
                                   name TEXT NOT NULL, chain_id INTEGER, store_id INTEGER, app TEXT, area_id INTEGER, url TEXT,
                                   UNIQUE (channel, name));
CREATE TABLE IF NOT EXISTS place_prices (place_id INTEGER NOT NULL, product_id INTEGER NOT NULL, day INTEGER NOT NULL,
                                   price INTEGER NOT NULL, promo INTEGER NOT NULL DEFAULT 0, regular INTEGER, low30 INTEGER,
                                   source TEXT NOT NULL CHECK (source IN ('receipt','report','site','archive','app')),
                                   PRIMARY KEY (place_id, product_id, day)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS product_sources (source TEXT NOT NULL, ext_key TEXT NOT NULL, product_id INTEGER NOT NULL,
                                   PRIMARY KEY (source, ext_key)) WITHOUT ROWID;

-- robot-only: statements waiting to be sent to D1 (not created in D1)
CREATE TABLE IF NOT EXISTS outbox (seq INTEGER PRIMARY KEY, sql TEXT NOT NULL);
-- robot-only: which products each chain sells (its own catalog, refreshed weekly), so chains are asked only about those
CREATE TABLE IF NOT EXISTS chain_products (chain_key TEXT NOT NULL, product_id INTEGER NOT NULL,
                                           PRIMARY KEY (chain_key, product_id)) WITHOUT ROWID;
-- robot-only: settings the robot keeps for itself (catalog files' hash, date of the Open Food Facts file)
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
