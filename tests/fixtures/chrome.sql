-- Observed column names; all rows are synthetic.
CREATE TABLE urls (
    id INTEGER PRIMARY KEY, url LONGVARCHAR, title LONGVARCHAR,
    visit_count INTEGER NOT NULL DEFAULT 0, typed_count INTEGER NOT NULL DEFAULT 0,
    last_visit_time INTEGER NOT NULL, hidden INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE visits (
    id INTEGER PRIMARY KEY, url INTEGER NOT NULL, visit_time INTEGER NOT NULL,
    from_visit INTEGER, external_referrer_url TEXT, transition INTEGER NOT NULL DEFAULT 0,
    segment_id INTEGER, visit_duration INTEGER NOT NULL DEFAULT 0,
    incremented_omnibox_typed_score BOOLEAN DEFAULT FALSE, opener_visit INTEGER,
    originator_cache_guid TEXT, originator_visit_id INTEGER, originator_from_visit INTEGER,
    originator_opener_visit INTEGER, is_known_to_sync BOOLEAN DEFAULT FALSE,
    consider_for_ntp_most_visited BOOLEAN DEFAULT FALSE,
    visited_link_id INTEGER NOT NULL DEFAULT 0, app_id TEXT
);
-- 2026-10-22 01:00:00Z, integer microseconds since 1601-01-01Z.
INSERT INTO urls(id,url,title,last_visit_time) VALUES
    (1,'https://example.invalid/article','合成页面标题',13437104400000000),
    (2,'https://mail.google.com/synthetic','黑名单测试',13437104400000000),
    (3,'file:///synthetic/private.txt','本地协议测试',13437104400000000);
INSERT INTO visits(id,url,visit_time,visit_duration,transition) VALUES
    (1,1,13437104400000000,2500000,1),
    (2,1,13437104400000000,1000000,0),
    (3,2,13437104400000000,0,0),
    (4,3,13437104400000000,0,0);
