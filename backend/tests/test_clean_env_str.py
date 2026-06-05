from datetime import datetime, timedelta

from jose import jwt

from app.config import clean_env_str, config


def test_clean_env_str_strips_wrapping_quotes():
    assert clean_env_str('"abc"') == "abc"
    assert clean_env_str("'abc'") == "abc"
    assert clean_env_str("  value  ") == "value"
    assert clean_env_str(None, "fallback") == "fallback"


def test_jwt_roundtrip_with_config_secret():
    token = jwt.encode(
        {
            "sub": "user-1",
            "exp": datetime.utcnow() + timedelta(minutes=5),
            "type": "access",
        },
        config.JWT_SECRET_KEY,
        algorithm=config.JWT_ALGORITHM,
    )
    payload = jwt.decode(token, config.JWT_SECRET_KEY, algorithms=[config.JWT_ALGORITHM])
    assert payload["sub"] == "user-1"
    assert payload["type"] == "access"
