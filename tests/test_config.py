import pytest

from lab import config


def test_secret_is_masked():
    s = config.Secret("FRED_API_KEY", "abc123supersecret")
    assert "abc123supersecret" not in repr(s)
    assert "abc123supersecret" not in str(s)
    assert "abc123supersecret" not in f"{s}"
    assert s.reveal() == "abc123supersecret"


def test_missing_secret_error_has_no_value(monkeypatch):
    monkeypatch.delenv("NOPE_KEY", raising=False)
    with pytest.raises(RuntimeError) as e:
        config.get_secret("NOPE_KEY")
    assert "NOPE_KEY" in str(e.value)


def test_dotenv_is_gitignored():
    lines = (config.ROOT / ".gitignore").read_text().splitlines()
    assert ".env" in lines
