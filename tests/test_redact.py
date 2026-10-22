import pytest

from aibrain.redact import redact, redact_value


@pytest.mark.parametrize("secret,normal", [
    ("sk-" + "A" * 24, "sk-short"),
    ("sk-ant-" + "B" * 24, "sk-ant-short"),
    ("ghp_" + "C" * 24, "ghp_short"),
    ("gho_" + "D" * 24, "gho_short"),
    ("github_pat_" + "E" * 24, "github_pat_short"),
    ("AKIA" + "1" * 16, "AKIA123"),
    ("-----BEGIN RSA PRIVATE KEY-----\nSYNTHETIC\n-----END RSA PRIVATE KEY-----", "-----BEGIN PUBLIC KEY-----\nSYNTHETIC\n-----END PUBLIC KEY-----"),
    ("xoxb-synthetic-123", "xoxb is a prefix"),
    ("eyJhbGciOiJub25lIn0.eyJzdWIiOiJmYWtlIn0.c3ludGhldGlj", "eyJnormaltext"),
    ('password: "fake value with spaces"', "password reset instructions"),
    ("passwd = fake-value", "passwd documentation"),
    ("secret: fake-value", "secret garden"),
    ("token=fake-value", "token count is 42"),
    ("api_key: fake-value", "api_key is a field name"),
    ("SERVICE_SECRET=fake-value", "SERVICE_HOST=example.invalid"),
    ("export SERVICE_TOKEN='fake with spaces'", "export SERVICE_PORT=1234"),
    ("SERVICE_KEY=fake-value", "SERVICE_MODE=offline"),
    ("SERVICE_PASSWORD=fake-value", "SERVICE_NAME=demo"),
])
def test_each_pattern_has_positive_and_negative(secret, normal):
    clean = redact(secret)
    assert "[REDACTED:" in clean
    assert clean != secret
    assert redact(normal) == normal
    assert redact(clean) == clean


def test_json_and_url_assignments_preserve_surrounding_text():
    assert redact('{"password":"fake","name":"demo"}') == '{"password":"[REDACTED:SECRET]","name":"demo"}'
    assert redact("https://example.invalid/?token=fake&topic=demo") == "https://example.invalid/?token=[REDACTED:SECRET]&topic=demo"


def test_recursive_metadata_and_sensitive_keys():
    value = {"tools": [{"path": "prefix sk-" + "A" * 24}], "selection": "password=fake", "api_key": "fake", "count": 2}
    clean = redact_value(value)
    assert clean["tools"][0]["path"] == "prefix [REDACTED:API_KEY]"
    assert clean["selection"] == "password=[REDACTED:ENV_SECRET]"
    assert clean["api_key"] == "[REDACTED:SECRET]"
    assert clean["count"] == 2
    assert value["api_key"] == "fake"


def test_private_keys_span_multiple_lines():
    assert redact("before\n-----BEGIN PRIVATE KEY-----\na\nb\n-----END PRIVATE KEY-----\nafter") == "before\n[REDACTED:PRIVATE_KEY]\nafter"
