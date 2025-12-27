"""Helper utility for GigaChat token management"""
import requests
import uuid
import logging
from typing import Optional
from app.config import config

logger = logging.getLogger(__name__)


def get_gigachat_access_token(
    authorization_key: Optional[str] = None,
    scope: Optional[str] = None
) -> Optional[str]:
    """
    Получить токен доступа GigaChat из ключа авторизации
    
    ВАЖНО: Обычно SDK автоматически получает токен, эта функция нужна только
    для тестирования или ручного управления токенами.
    
    Args:
        authorization_key: Ключ авторизации (base64 encoded ClientID:ClientSecret)
                          Если не указан, берется из config.GIGACHAT_CREDENTIALS
        scope: Scope для токена (по умолчанию из config.GIGACHAT_SCOPE)
               GIGACHAT_API_PERS для физических лиц
    
    Returns:
        Access token или None в случае ошибки
    
    Документация:
    https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/post-token
    """
    auth_key = authorization_key or config.GIGACHAT_CREDENTIALS
    token_scope = scope or config.GIGACHAT_SCOPE
    
    if not auth_key:
        logger.error("GIGACHAT_CREDENTIALS not set")
        return None
    
    # Генерируем уникальный идентификатор запроса
    rquid = str(uuid.uuid4())
    
    try:
        response = requests.post(
            'https://ngw.devices.sberbank.ru:9443/api/v2/oauth',
            headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/json',
                'RqUID': rquid,
                'Authorization': f'Basic {auth_key}'
            },
            data={'scope': token_scope},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            access_token = data.get('access_token')
            expires_in = data.get('expires_in', 1800)  # По умолчанию 30 минут
            
            logger.info(
                f"✅ Получен токен доступа GigaChat (действителен {expires_in} секунд)"
            )
            return access_token
        else:
            logger.error(
                f"❌ Ошибка получения токена: {response.status_code} - {response.text}"
            )
            return None
            
    except Exception as e:
        logger.error(f"❌ Исключение при получении токена: {e}", exc_info=True)
        return None


def test_gigachat_credentials(authorization_key: Optional[str] = None) -> bool:
    """
    Протестировать ключ авторизации GigaChat
    
    Args:
        authorization_key: Ключ авторизации (опционально, берется из config)
    
    Returns:
        True если ключ валидный, False иначе
    """
    token = get_gigachat_access_token(authorization_key)
    return token is not None

