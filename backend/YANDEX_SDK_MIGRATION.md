# 🔄 Миграция на официальный Yandex Cloud ML SDK

## ✅ Что изменилось

Вместо прямых API вызовов через `requests` теперь используется **официальный Yandex Cloud ML SDK**:
- https://github.com/yandex-cloud/yandex-cloud-ml-sdk

## 🎯 Преимущества

1. **Автоматическая аутентификация** - SDK сам выбирает метод (API ключ, IAM токен, OAuth)
2. **Обработка ошибок** - встроенные retry политики и обработка ошибок
3. **LangChain интеграция** - готовые обертки для LangChain
4. **Надежность** - официальная поддержка от Yandex
5. **Проще код** - меньше boilerplate кода

## 📦 Установка

SDK уже добавлен в `requirements.txt`:
```
yandex-cloud-ml-sdk==0.17.1
```

Установи:
```bash
pip install -r requirements.txt
```

## 🔧 Что изменилось в коде

### 1. YandexGPT (`yandex_llm.py`)

**Было:**
```python
# Прямые API вызовы через requests
url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
headers = {"Authorization": f"Bearer {token}", ...}
response = requests.post(url, json=payload, headers=headers)
```

**Стало:**
```python
# Использование официального SDK
from yandex_cloud_ml_sdk import YCloudML
sdk = YCloudML(folder_id=..., auth=APIKeyAuth(api_key))
model = sdk.models.completions('yandexgpt')
result = model.run(text)
```

### 2. Embeddings (`yandex_embeddings.py`)

**Было:**
```python
# Прямые API вызовы
url = "https://llm.api.cloud.yandex.net/foundationModels/v1/textEmbedding"
response = requests.post(url, json=payload, headers=headers)
```

**Стало:**
```python
# Использование официального SDK
sdk = YCloudML(folder_id=..., auth=APIKeyAuth(api_key))
embeddings_model = sdk.models.text_embeddings('yandexgpt')
result = embeddings_model.run(text)
```

## 🔑 Аутентификация

SDK автоматически поддерживает:
- ✅ API ключ (рекомендуется)
- ✅ IAM токен
- ✅ OAuth токен
- ✅ Service Account ключ
- ✅ Metadata service (для Yandex Cloud VM)

Код автоматически использует API ключ если доступен, иначе IAM токен.

## 📝 Переменные окружения

Ничего не изменилось! Используй те же переменные:

```bash
# Вариант 1: API ключ (рекомендуется)
YANDEX_API_KEY=AQVNxxxxxxxxxxxxx

# Вариант 2: IAM токен
YANDEX_IAM_TOKEN=t1.xxxxxxxxxxxxx

# Опционально
YANDEX_FOLDER_ID=b1gxxxxxxxxxxxxx
```

## 🧪 Тестирование

После установки SDK:

1. Перезапусти backend
2. Проверь логи - должны быть:
   ```
   ✅ Using Yandex API key for authentication
   ✅ Using Yandex API key for embeddings
   ```

3. Протестируй в чате:
   ```
   👤: "Привет, как дела?"
   🤖: (должен ответить через YandexGPT)
   ```

## 🔗 Полезные ссылки

- [Официальный SDK GitHub](https://github.com/yandex-cloud/yandex-cloud-ml-sdk)
- [Документация SDK](https://yandex.cloud/en/docs/ai-studio/sdk/)
- [Примеры использования](https://github.com/yandex-cloud/yandex-cloud-ml-sdk/tree/master/examples)

## ✅ Готово!

Код теперь использует официальный SDK - надежнее и проще!
