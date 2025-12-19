# Руководство по интеграции Yandex.Cloud и Yandex.AI Studio

## 🚀 Быстрый старт

Это краткое практическое руководство по интеграции Yandex.Cloud и Yandex.AI Studio в проект Legal AI Vault.

Полный анализ и детали см. в [YANDEX_CLOUD_FULL_ANALYSIS.md](./YANDEX_CLOUD_FULL_ANALYSIS.md)

---

## 1. Настройка Yandex.Cloud

### 1.1 Создание аккаунта и получение ключей

1. Зарегистрируйтесь на https://cloud.yandex.ru/
2. Создайте каталог (folder)
3. Создайте сервисный аккаунт с правами:
   - `ai.languageModels.user` - для YandexGPT
   - `storage.editor` - для Object Storage
   - `vpc.user` - для сетей
4. Создайте API ключ для сервисного аккаунта
5. Запомните Folder ID (из URL каталога)

---

## 2. Интеграция YandexGPT

### 2.1 Обновление конфигурации

**backend/app/config.py:**
```python
# Добавить в класс Config:
# Yandex AI Studio
YANDEX_API_KEY: str = os.getenv("YANDEX_API_KEY", "")
YANDEX_FOLDER_ID: str = os.getenv("YANDEX_FOLDER_ID", "")
YANDEX_BASE_URL: str = os.getenv(
    "YANDEX_BASE_URL", 
    "https://llm.api.cloud.yandex.net/v1"
)
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "yandex")  # yandex | openrouter
YANDEX_MODEL: str = os.getenv("YANDEX_MODEL", "yandexgpt")  # yandexgpt | yandexgpt-lite
```

### 2.2 Создание провайдера YandexGPT

**backend/app/services/llm_providers/__init__.py:**
```python
# Создать файл
```

**backend/app/services/llm_providers/yandex_provider.py:**
```python
"""YandexGPT provider for LLM operations"""
from typing import List, Dict, Any
from langchain_openai import ChatOpenAI
from app.config import config
import logging

logger = logging.getLogger(__name__)


class YandexGPTProvider:
    """YandexGPT provider using OpenAI-compatible API"""
    
    def __init__(self):
        """Initialize YandexGPT provider"""
        if not config.YANDEX_API_KEY or not config.YANDEX_FOLDER_ID:
            raise ValueError(
                "YANDEX_API_KEY and YANDEX_FOLDER_ID must be set in environment"
            )
        
        self.llm = ChatOpenAI(
            model=config.YANDEX_MODEL,
            openai_api_key=config.YANDEX_API_KEY,
            openai_api_base=config.YANDEX_BASE_URL,
            temperature=0.7,
            max_tokens=2000,
            timeout=60.0,
            extra_headers={
                "x-folder-id": config.YANDEX_FOLDER_ID
            }
        )
        logger.info(f"✅ YandexGPT provider initialized with model: {config.YANDEX_MODEL}")
    
    def generate(self, messages: List[Dict[str, str]]) -> str:
        """Generate text using YandexGPT"""
        try:
            response = self.llm.invoke(messages)
            return response.content
        except Exception as e:
            logger.error(f"Ошибка при генерации через YandexGPT: {e}", exc_info=True)
            raise
    
    def stream(self, messages: List[Dict[str, str]]):
        """Stream text generation using YandexGPT"""
        try:
            for chunk in self.llm.stream(messages):
                if chunk.content:
                    yield chunk.content
        except Exception as e:
            logger.error(f"Ошибка при потоковой генерации через YandexGPT: {e}", exc_info=True)
            raise
```

### 2.3 Обновление LLMService

**backend/app/services/llm_service.py:**
```python
"""LLM service with provider abstraction"""
from typing import List, Dict, Any, Optional, Tuple
from langchain_core.documents import Document
from app.config import config
from app.services.llm_providers.yandex_provider import YandexGPTProvider
import logging

logger = logging.getLogger(__name__)


class LLMService:
    """Service for LLM operations with provider abstraction"""
    
    def __init__(self):
        """Initialize LLM service with selected provider"""
        provider_name = config.LLM_PROVIDER.lower()
        
        if provider_name == "yandex":
            try:
                self.provider = YandexGPTProvider()
                logger.info("✅ Using YandexGPT provider")
            except Exception as e:
                logger.warning(f"Failed to initialize YandexGPT: {e}. Falling back to OpenRouter.")
                # Fallback to OpenRouter (старая реализация)
                from langchain_openai import ChatOpenAI
                self.provider = ChatOpenAI(
                    model=config.OPENROUTER_MODEL,
                    openai_api_key=config.OPENROUTER_API_KEY,
                    openai_api_base=config.OPENROUTER_BASE_URL,
                    temperature=0.7,
                    max_tokens=2000,
                    timeout=60.0
                )
        else:
            # OpenRouter (старая реализация)
            from langchain_openai import ChatOpenAI
            self.provider = ChatOpenAI(
                model=config.OPENROUTER_MODEL,
                openai_api_key=config.OPENROUTER_API_KEY,
                openai_api_base=config.OPENROUTER_BASE_URL,
                temperature=0.7,
                max_tokens=2000,
                timeout=60.0
            )
            logger.info("✅ Using OpenRouter provider")
    
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> str:
        """Generate text using selected LLM provider"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        if hasattr(self.provider, 'generate'):
            # Новый провайдер с методом generate
            return self.provider.generate(messages)
        else:
            # Старый провайдер (ChatOpenAI напрямую)
            response = self.provider.invoke(messages)
            return response.content
    
    # Остальные методы остаются без изменений...
    def generate_with_sources(
        self,
        system_prompt: str,
        user_prompt: str,
        documents: List[Document],
        temperature: float = 0.7
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Generate answer with source references"""
        sources_text = self._format_sources_for_prompt(documents)
        
        full_system_prompt = f"""{system_prompt}

ВАЖНО: ВСЕГДА указывай конкретные источники в формате:
[Документ: filename.pdf, стр. 5, строки 12-15]

Источники:
{sources_text}
"""
        
        answer = self.generate(full_system_prompt, user_prompt, temperature)
        sources = self._format_sources(documents)
        
        return answer, sources
    
    def _format_sources_for_prompt(self, documents: List[Document]) -> str:
        """Format sources as text for prompt"""
        formatted = []
        for i, doc in enumerate(documents, 1):
            metadata = doc.metadata
            source_file = metadata.get("source_file", "unknown")
            source_page = metadata.get("source_page")
            source_line = metadata.get("source_start_line")
            
            source_ref = f"[Источник {i}: {source_file}"
            if source_page:
                source_ref += f", стр. {source_page}"
            if source_line:
                source_ref += f", строка {source_line}"
            source_ref += "]"
            
            formatted.append(f"{source_ref}\n{doc.page_content}")
        
        return "\n\n".join(formatted)
    
    def _format_sources(self, documents: List[Document]) -> List[Dict[str, Any]]:
        """Format source documents"""
        sources = []
        for doc in documents:
            metadata = doc.metadata
            source = {
                "file": metadata.get("source_file", "unknown"),
                "page": metadata.get("source_page"),
                "chunk_index": metadata.get("chunk_index"),
                "start_line": metadata.get("source_start_line"),
                "end_line": metadata.get("source_end_line"),
                "text_preview": doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content,
                "similarity_score": metadata.get("similarity_score")
            }
            sources.append(source)
        return sources
```

### 2.4 Обновление .env

```env
# Yandex AI Studio
YANDEX_API_KEY=AQVNxxxxxxxxxxxxxxxxxxxxx
YANDEX_FOLDER_ID=b1gxxxxxxxxxxxxx
YANDEX_MODEL=yandexgpt
LLM_PROVIDER=yandex

# OpenRouter (опционально, для fallback)
OPENROUTER_API_KEY=sk-or-xxxxxxxxxxxxxxxx
OPENROUTER_MODEL=openrouter/auto
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

---

## 3. Интеграция Object Storage

### 3.1 Установка зависимостей

```bash
pip install boto3
# или
pip install yandex-cloud-sdk
```

### 3.2 Обновление конфигурации

**backend/app/config.py:**
```python
# Object Storage
YANDEX_STORAGE_BUCKET: str = os.getenv("YANDEX_STORAGE_BUCKET", "")
YANDEX_STORAGE_ACCESS_KEY: str = os.getenv("YANDEX_STORAGE_ACCESS_KEY", "")
YANDEX_STORAGE_SECRET_KEY: str = os.getenv("YANDEX_STORAGE_SECRET_KEY", "")
YANDEX_STORAGE_ENDPOINT: str = os.getenv(
    "YANDEX_STORAGE_ENDPOINT", 
    "https://storage.yandexcloud.net"
)
```

### 3.3 Создание сервиса для Object Storage

**backend/app/services/storage_service.py:**
```python
"""Service for working with Yandex Object Storage"""
import boto3
from botocore.client import Config
from app.config import config
import logging
from typing import Optional, BinaryIO

logger = logging.getLogger(__name__)


class StorageService:
    """Service for file storage in Yandex Object Storage"""
    
    def __init__(self):
        """Initialize storage service"""
        if not all([
            config.YANDEX_STORAGE_BUCKET,
            config.YANDEX_STORAGE_ACCESS_KEY,
            config.YANDEX_STORAGE_SECRET_KEY
        ]):
            logger.warning("Object Storage credentials not configured. Using local storage.")
            self.storage_enabled = False
            return
        
        self.storage_enabled = True
        self.s3_client = boto3.client(
            's3',
            endpoint_url=config.YANDEX_STORAGE_ENDPOINT,
            aws_access_key_id=config.YANDEX_STORAGE_ACCESS_KEY,
            aws_secret_access_key=config.YANDEX_STORAGE_SECRET_KEY,
            config=Config(signature_version='s3v4'),
            region_name='ru-central1'
        )
        self.bucket_name = config.YANDEX_STORAGE_BUCKET
        logger.info(f"✅ Object Storage initialized: {self.bucket_name}")
    
    def upload_file(self, file_obj: BinaryIO, file_path: str, content_type: str = None) -> str:
        """Upload file to Object Storage"""
        if not self.storage_enabled:
            raise RuntimeError("Object Storage is not configured")
        
        try:
            extra_args = {}
            if content_type:
                extra_args['ContentType'] = content_type
            
            self.s3_client.upload_fileobj(
                file_obj,
                self.bucket_name,
                file_path,
                ExtraArgs=extra_args
            )
            
            # Generate public URL (или signed URL для безопасности)
            url = f"{config.YANDEX_STORAGE_ENDPOINT}/{self.bucket_name}/{file_path}"
            logger.info(f"File uploaded: {file_path}")
            return url
        except Exception as e:
            logger.error(f"Error uploading file {file_path}: {e}", exc_info=True)
            raise
    
    def download_file(self, file_path: str) -> bytes:
        """Download file from Object Storage"""
        if not self.storage_enabled:
            raise RuntimeError("Object Storage is not configured")
        
        try:
            response = self.s3_client.get_object(
                Bucket=self.bucket_name,
                Key=file_path
            )
            return response['Body'].read()
        except Exception as e:
            logger.error(f"Error downloading file {file_path}: {e}", exc_info=True)
            raise
    
    def delete_file(self, file_path: str) -> bool:
        """Delete file from Object Storage"""
        if not self.storage_enabled:
            raise RuntimeError("Object Storage is not configured")
        
        try:
            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=file_path
            )
            logger.info(f"File deleted: {file_path}")
            return True
        except Exception as e:
            logger.error(f"Error deleting file {file_path}: {e}", exc_info=True)
            return False
    
    def get_signed_url(self, file_path: str, expires_in: int = 3600) -> str:
        """Generate signed URL for temporary access"""
        if not self.storage_enabled:
            raise RuntimeError("Object Storage is not configured")
        
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': file_path},
                ExpiresIn=expires_in
            )
            return url
        except Exception as e:
            logger.error(f"Error generating signed URL for {file_path}: {e}", exc_info=True)
            raise


# Singleton instance
storage_service = StorageService()
```

### 3.4 Обновление upload endpoint

**backend/app/routes/upload.py:**
```python
# Добавить в начало файла:
from app.services.storage_service import storage_service

# Обновить функцию загрузки файлов:
@router.post("/upload")
async def upload_files(
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # ... существующий код ...
    
    # После обработки файла, загрузить в Object Storage:
    if storage_service.storage_enabled:
        # Генерируем путь в storage
        storage_path = f"cases/{case_id}/{file.filename}"
        
        # Загружаем в Object Storage
        file_obj.seek(0)  # Reset file pointer
        storage_url = storage_service.upload_file(
            file_obj,
            storage_path,
            content_type=file.content_type
        )
        
        # Сохраняем URL в базе данных
        file_record.storage_url = storage_url
    
    # ... остальной код ...
```

---

## 4. Настройка Managed PostgreSQL

### 4.1 Создание кластера PostgreSQL в Yandex.Cloud

1. Перейдите в Yandex.Cloud Console
2. Выберите "Managed Service for PostgreSQL"
3. Создайте кластер:
   - Версия: PostgreSQL 15 или 16
   - Класс хоста: s2.micro (для тестирования) или s2.medium (для production)
   - Размер диска: 20 GB (минимум) или больше
   - Репликация: включена (для production)
4. Создайте базу данных и пользователя
5. Получите строку подключения

### 4.2 Обновление DATABASE_URL

```env
# Формат для Yandex Managed PostgreSQL:
DATABASE_URL=postgresql://username:password@c-xxx.rw.mdb.yandexcloud.net:6432/legal_ai_vault?sslmode=require

# Где:
# - c-xxx - ID кластера
# - rw.mdb.yandexcloud.net - endpoint для чтения/записи
# - 6432 - порт PostgreSQL
# - sslmode=require - обязательно для Managed PostgreSQL
```

### 4.3 Обновление подключения в database.py

**backend/app/utils/database.py:**
```python
# URL уже должен работать с SSL, но можно добавить явную настройку:
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

def create_db_engine() -> Engine:
    """Create database engine with SSL for Yandex Managed PostgreSQL"""
    engine = create_engine(
        config.DATABASE_URL,
        echo=False,
        connect_args={
            "sslmode": "require"  # Для Yandex Managed PostgreSQL
        } if "yandexcloud.net" in config.DATABASE_URL else {}
    )
    return engine

# Обновить engine:
engine = create_db_engine()
```

---

## 5. Тестирование

### 5.1 Тест YandexGPT

```python
# test_yandex_gpt.py
from app.services.llm_providers.yandex_provider import YandexGPTProvider

provider = YandexGPTProvider()
messages = [
    {"role": "system", "content": "Ты помощник юриста."},
    {"role": "user", "content": "Что такое договор купли-продажи?"}
]

response = provider.generate(messages)
print(response)
```

### 5.2 Тест Object Storage

```python
# test_storage.py
from app.services.storage_service import storage_service

# Тест загрузки
with open("test.pdf", "rb") as f:
    url = storage_service.upload_file(f, "test/test.pdf", "application/pdf")
    print(f"Uploaded: {url}")

# Тест скачивания
data = storage_service.download_file("test/test.pdf")
with open("downloaded_test.pdf", "wb") as f:
    f.write(data)
```

---

## 6. Переменные окружения для production

```env
# ============================================
# Yandex.Cloud Configuration
# ============================================

# Yandex AI Studio
YANDEX_API_KEY=AQVNxxxxxxxxxxxxxxxxxxxxx
YANDEX_FOLDER_ID=b1gxxxxxxxxxxxxx
YANDEX_MODEL=yandexgpt
LLM_PROVIDER=yandex

# Yandex Object Storage
YANDEX_STORAGE_BUCKET=legal-ai-vault-documents
YANDEX_STORAGE_ACCESS_KEY=YCAxxxxxxxxxxxxxxx
YANDEX_STORAGE_SECRET_KEY=YCMxxxxxxxxxxxxxxx
YANDEX_STORAGE_ENDPOINT=https://storage.yandexcloud.net

# Yandex Managed PostgreSQL
DATABASE_URL=postgresql://user:password@c-xxx.rw.mdb.yandexcloud.net:6432/legal_ai_vault?sslmode=require

# ============================================
# Other settings
# ============================================
JWT_SECRET_KEY=your-very-secure-secret-key-min-32-chars
CORS_ORIGINS=https://yourdomain.com
```

---

## 7. Развертывание на Yandex Compute Cloud

### 7.1 Создание VM

1. Перейдите в Yandex.Cloud Console
2. Выберите "Compute Cloud" → "Instances"
3. Создайте виртуальную машину:
   - Платформа: Intel Broadwell или newer
   - vCPU: 2-4
   - RAM: 4-8 GB
   - Диск: 50-100 GB SSD
   - Образ: Ubuntu 22.04 LTS
4. Настройте сеть и firewall правила

### 7.2 Установка зависимостей на VM

```bash
# Подключитесь к VM через SSH
ssh user@vm-ip

# Установите Python и зависимости
sudo apt update
sudo apt install -y python3.10 python3-pip postgresql-client

# Установите зависимости проекта
cd /path/to/project/backend
pip3 install -r requirements.txt

# Настройте systemd service для FastAPI
sudo nano /etc/systemd/system/legal-ai-vault.service
```

**/etc/systemd/system/legal-ai-vault.service:**
```ini
[Unit]
Description=Legal AI Vault Backend
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/project/backend
Environment="PATH=/usr/bin:/usr/local/bin"
ExecStart=/usr/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
# Запустите сервис
sudo systemctl daemon-reload
sudo systemctl enable legal-ai-vault
sudo systemctl start legal-ai-vault
```

### 7.3 Настройка Application Load Balancer

1. Создайте Target Group с вашими VM
2. Создайте Backend Group
3. Создайте HTTP Router
4. Настройте Listener на порт 80/443
5. Получите IP адрес Load Balancer

---

## 8. Мониторинг и алерты

### 8.1 Настройка Yandex Monitoring

1. Перейдите в Yandex.Cloud Console → Monitoring
2. Создайте дашборды для:
   - Загрузка CPU/RAM VM
   - Использование диска
   - Количество запросов к API
   - Латентность LLM запросов
3. Настройте алерты на:
   - Высокую загрузку CPU (>80%)
   - Низкий свободный диск (<10%)
   - Ошибки в API (>5%)
   - Высокую латентность LLM (>5 сек)

---

## ✅ Чеклист внедрения

### Этап 1: YandexGPT
- [ ] Создан аккаунт Yandex.Cloud
- [ ] Получены API ключи
- [ ] Создан YandexGPTProvider
- [ ] Обновлен LLMService
- [ ] Протестирован YandexGPT
- [ ] Обновлена конфигурация

### Этап 2: Object Storage
- [ ] Создан бакет в Object Storage
- [ ] Получены ключи доступа
- [ ] Создан StorageService
- [ ] Обновлен upload endpoint
- [ ] Протестирована загрузка/скачивание

### Этап 3: Managed PostgreSQL
- [ ] Создан кластер PostgreSQL
- [ ] Обновлен DATABASE_URL
- [ ] Выполнена миграция данных
- [ ] Протестировано подключение

### Этап 4: Развертывание
- [ ] Создана VM в Compute Cloud
- [ ] Настроен Application Load Balancer
- [ ] Развернуто приложение
- [ ] Настроен мониторинг

---

## 📞 Поддержка

- **Документация Yandex.Cloud**: https://yandex.cloud/ru/docs/
- **Документация Yandex.AI Studio**: https://yandex.cloud/ru/docs/ai-studio/
- **Техподдержка**: через консоль Yandex.Cloud

---

*Обновлено: 2024*
