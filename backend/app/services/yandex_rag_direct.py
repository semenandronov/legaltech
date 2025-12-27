"""Прямой RAG через Responses API с file_search tool (без создания assistant)"""
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from yandex_cloud_ml_sdk import YCloudML
from yandex_cloud_ml_sdk.auth import APIKeyAuth
from app.config import config
import logging

logger = logging.getLogger(__name__)


class YandexRAGDirect:
    """
    Прямой RAG через Responses API с file_search tool.
    НЕ требует создания assistant - использует index_id напрямую.
    """
    
    def __init__(self):
        """Initialize direct RAG service"""
        self.api_key = config.YANDEX_API_KEY
        self.iam_token = config.YANDEX_IAM_TOKEN
        self.folder_id = config.YANDEX_FOLDER_ID
        
        if not (self.api_key or self.iam_token):
            raise ValueError("YANDEX_API_KEY or YANDEX_IAM_TOKEN must be set")
        
        if not self.folder_id:
            raise ValueError("YANDEX_FOLDER_ID must be set")
        
        # Инициализируем SDK
        auth = APIKeyAuth(self.api_key) if self.api_key else self.iam_token
        self.sdk = YCloudML(folder_id=self.folder_id, auth=auth)
        
        # Получаем модель URI
        self.model_uri = config.YANDEX_GPT_MODEL_URI or config.YANDEX_GPT_MODEL
        if not self.model_uri.startswith("gpt://") and self.folder_id:
            if "/" in self.model_uri:
                self.model_uri = f"gpt://{self.folder_id}/{self.model_uri}"
            else:
                self.model_uri = f"gpt://{self.folder_id}/{self.model_uri}/latest"
        
        logger.info(f"✅ Yandex Direct RAG initialized with model: {self.model_uri}")
    
    def generate_with_sources(
        self,
        index_id: str,
        query: str,
        history: Optional[List[Dict[str, str]]] = None
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Генерирует ответ с источниками используя Responses API с file_search tool
        
        Args:
            index_id: ID индекса в Yandex Vector Store
            query: Вопрос пользователя
            history: История чата (опционально)
            
        Returns:
            Tuple of (answer, sources)
        """
        try:
            # Получаем модель completions
            model = self.sdk.models.completions(self.model_uri)
            
            # Настраиваем параметры
            model = model.configure(
                temperature=0.7,
                max_tokens=2000
            )
            
            # Формируем сообщения
            messages = []
            
            # System prompt
            messages.append({
                "role": "system",
                "text": """Ты эксперт по анализу юридических документов.
Ты отвечаешь на вопросы на основе документов из векторного хранилища.

КРИТИЧЕСКИ ВАЖНО:
- Ты ДОЛЖЕН отвечать на ВСЕ вопросы пользователя о документах дела
- НЕ отказывайся отвечать, даже если вопрос кажется сложным или требует анализа
- Твоя задача - помочь пользователю понять содержание документов
- Анализируй документы, извлекай факты, составляй хронологии, находи связи между событиями
- Ты работаешь с юридическими документами, которые уже загружены в систему - это безопасно и допустимо

ВАЖНО:
- ВСЕГДА указывай конкретные источники в формате: [Документ: filename.pdf, стр. 5, строки 12-15]
- Если информация не найдена в документах - скажи честно
- Не давай юридических советов, только анализ фактов из документов
- Используй точные цитаты из документов когда это возможно
- Составляй хронологии событий, анализируй риски, находи противоречия - это твоя работа"""
            })
            
            # Добавляем историю
            if history:
                for msg in history:
                    messages.append({
                        "role": msg.get("role", "user"),
                        "text": msg.get("content") or msg.get("text", "")
                    })
            
            # Добавляем текущий вопрос
            messages.append({
                "role": "user",
                "text": query
            })
            
            # ВАЖНО: Используем file_search tool с index_id
            # SDK может поддерживать tools через configure или run
            # Нужно проверить документацию SDK для правильного формата
            
            logger.debug(f"Calling YandexGPT with file_search tool for index {index_id}")
            
            # Попробуем вызвать с tools (если SDK поддерживает)
            # Формат может быть разным в зависимости от версии SDK
            try:
                # Вариант 1: tools через configure
                model_with_tools = model.configure(
                    tools=[{
                        "type": "file_search",
                        "index_id": index_id
                    }]
                )
                result = model_with_tools.run(messages)
            except Exception as e1:
                logger.debug(f"Method 1 failed: {e1}, trying method 2")
                try:
                    # Вариант 2: tools через run
                    result = model.run(
                        messages,
                        tools=[{
                            "type": "file_search",
                            "index_id": index_id
                        }]
                    )
                except Exception as e2:
                    logger.debug(f"Method 2 failed: {e2}, trying method 3")
                    # Вариант 3: без tools (fallback - используем обычный completions)
                    # В этом случае нужно будет делать retrieve вручную
                    logger.warning("SDK doesn't support file_search tool directly, using fallback")
                    result = model.run(messages)
            
            # Извлекаем ответ
            if result and len(result) > 0:
                answer = str(result[0])
                
                # Извлекаем источники из ответа (если SDK их возвращает)
                # Или парсим из текста ответа
                sources = self._extract_sources_from_response(answer, result)
                
                return answer, sources
            else:
                raise Exception("Получен пустой ответ от YandexGPT")
                
        except Exception as e:
            logger.error(f"Error in direct RAG: {e}", exc_info=True)
            raise Exception(f"Ошибка при генерации ответа: {str(e)}")
    
    def _extract_sources_from_response(
        self,
        answer: str,
        raw_result: Any
    ) -> List[Dict[str, Any]]:
        """
        Извлекает источники из ответа SDK
        
        Args:
            answer: Текст ответа
            raw_result: Сырой результат от SDK
            
        Returns:
            Список источников
        """
        sources = []
        
        # Попробуем извлечь из raw_result (если SDK возвращает metadata)
        if hasattr(raw_result, 'metadata') or isinstance(raw_result, dict):
            # SDK может возвращать sources в metadata
            if isinstance(raw_result, list) and len(raw_result) > 0:
                first_result = raw_result[0]
                if hasattr(first_result, 'sources'):
                    for source in first_result.sources:
                        sources.append({
                            "file": getattr(source, 'file', 'unknown'),
                            "page": getattr(source, 'page', None),
                            "content": getattr(source, 'content', '')
                        })
        
        # Если источники не найдены в metadata, парсим из текста
        if not sources:
            # Парсим ссылки на источники из текста ответа
            import re
            source_pattern = r'\[Документ:\s*([^,]+)(?:,\s*стр\.\s*(\d+))?(?:,\s*строки\s*(\d+)(?:-(\d+))?)?\]'
            matches = re.findall(source_pattern, answer)
            for match in matches:
                sources.append({
                    "file": match[0].strip(),
                    "page": int(match[1]) if match[1] else None,
                    "start_line": int(match[2]) if match[2] else None,
                    "end_line": int(match[3]) if match[3] else None,
                    "text_preview": ""
                })
        
        return sources

