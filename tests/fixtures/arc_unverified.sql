-- Hypothetical Chromium subset, not verified against a local Arc installation.
CREATE TABLE urls(id INTEGER PRIMARY KEY, url TEXT, title TEXT);
CREATE TABLE visits(id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER,
                    visit_duration INTEGER, transition INTEGER);
INSERT INTO urls VALUES(1,'https://arc.example.invalid/demo','合成 Arc 页面');
INSERT INTO visits VALUES(1,1,13437104400000000,1000000,1);
