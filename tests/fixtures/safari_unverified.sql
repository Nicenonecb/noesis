-- Hypothetical schema: real Safari access was denied during M0.
CREATE TABLE history_items(id INTEGER PRIMARY KEY, url TEXT);
CREATE TABLE history_visits(id INTEGER PRIMARY KEY, history_item INTEGER,
                           visit_time REAL, title TEXT);
INSERT INTO history_items VALUES(1,'https://safari.example.invalid/demo');
-- 2026-10-22 01:00:00Z, seconds since 2001-01-01Z.
INSERT INTO history_visits VALUES(1,1,814323600.0,'合成 Safari 页面');
