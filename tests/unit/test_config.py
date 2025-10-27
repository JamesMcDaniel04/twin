from backend.core.config import get_settings


def test_settings_defaults():
    settings = get_settings()
    assert settings.API_TITLE == "TwinOps API"
