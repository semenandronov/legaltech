"""Yandex AI Studio Assistant service for RAG-ассистент"""
import requests
import logging
from typing import List, Dict, Any, Optional
from app.config import config as app_config

logger = logging.getLogger(__name__)


class YandexAssistantService:
    """Service for Yandex AI Studio Assistant API"""
    
    def __init__(self):
        """Initialize Yandex Assistant service"""
        self.api_key = app_config.YANDEX_API_KEY
        self.iam_token = app_config.YANDEX_IAM_TOKEN
        self.folder_id = app_config.YANDEX_FOLDER_ID
        
        # Используем API ключ если есть, иначе IAM токен
        self.auth_token = self.api_key or self.iam_token
        self.use_api_key = bool(self.api_key)
        
        if not self.auth_token:
            logger.warning(
                "YANDEX_API_KEY or YANDEX_IAM_TOKEN not set. "
                "Yandex Assistant service will not work."
            )
        
        if not self.folder_id:
            logger.warning(
                "YANDEX_FOLDER_ID not set. "
                "Yandex Assistant service requires folder_id."
            )
        
        # Base URL for Yandex AI Studio API
        self.base_url = "https://llm.api.cloud.yandex.net"
    
    def _get_headers(self) -> Dict[str, str]:
        """Get HTTP headers for API requests"""
        if self.use_api_key:
            auth_header = f"Api-Key {self.api_key}"
        else:
            auth_header = f"Bearer {self.iam_token}"
        
        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json"
        }
        
        if self.folder_id:
            headers["x-folder-id"] = self.folder_id
        
        return headers
    
    def create_assistant(self, case_id: str, index_id: str, config: Dict[str, Any] = None) -> str:
        """
        Create AI assistant with vector store tool
        
        Args:
            case_id: Case identifier
            index_id: Index identifier to use with Vector Store tool
            config: Optional assistant configuration
        
        Returns:
            assistant_id: ID of created assistant
        
        Note: This is a placeholder implementation. Actual API endpoint
        should be verified with Yandex AI Studio documentation.
        """
        if not self.auth_token or not self.folder_id:
            raise ValueError(
                "YANDEX_API_KEY/YANDEX_IAM_TOKEN and YANDEX_FOLDER_ID must be set"
            )
        
        assistant_name = config.get("name") if config else None
        if not assistant_name:
            assistant_name = f"legal_ai_vault_case_{case_id}"
        
        # TODO: Verify actual API endpoint with Yandex AI Studio documentation
        # This is a placeholder based on typical assistant API patterns
        url = f"{self.base_url}/foundationModels/v1/assistants"
        
        # Assistant configuration with Vector Store tool
        # Используем полный URI модели, если указан, иначе fallback на короткое имя
        model_config = config.get("model") if config else None
        if not model_config:
            model_config = app_config.YANDEX_GPT_MODEL_URI or app_config.YANDEX_GPT_MODEL
        # Если это короткое имя и есть folder_id, формируем полный URI
        if not model_config.startswith("gpt://") and app_config.YANDEX_FOLDER_ID:
            if "/" in model_config:
                model_config = f"gpt://{app_config.YANDEX_FOLDER_ID}/{model_config}"
            else:
                model_config = f"gpt://{app_config.YANDEX_FOLDER_ID}/{model_config}/latest"
        
        assistant_config = {
            "name": assistant_name,
            "description": f"Legal AI Assistant for case {case_id}",
            "model": model_config,
            "tools": [
                {
                    "type": "vector_store",
                    "index_id": index_id
                }
            ],
            "system_prompt": config.get(
                "system_prompt",
                """Ты эксперт по анализу юридических документов.
Ты отвечаешь на вопросы на основе документов из векторного хранилища.

ВАЖНО:
- ВСЕГДА указывай конкретные источники в формате: [Документ: filename.pdf, стр. 5, строки 12-15]
- Если информация не найдена в документах - скажи честно
- Не давай юридических советов, только анализ фактов из документов
- Используй точные цитаты из документов когда это возможно"""
            )
        }
        
        # Merge with custom config if provided
        if config:
            assistant_config.update({k: v for k, v in config.items() if k not in ["name", "model", "system_prompt"]})
        
        payload = {
            **assistant_config,
            "folder_id": self.folder_id
        }
        
        try:
            logger.info(f"Creating assistant '{assistant_name}' for case {case_id} with index {index_id}")
            response = requests.post(url, json=payload, headers=self._get_headers(), timeout=30)
            response.raise_for_status()
            
            result = response.json()
            
            # Extract assistant_id from response
            # Actual response format should be verified with documentation
            assistant_id = result.get("id") or result.get("assistant_id") or result.get("assistantId")
            
            if not assistant_id:
                logger.error(f"Unexpected response format from Yandex Assistant API: {result}")
                raise ValueError("Failed to extract assistant_id from API response")
            
            logger.info(f"✅ Created assistant {assistant_id} for case {case_id}")
            return assistant_id
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error creating assistant via Yandex AI Studio API: {e}", exc_info=True)
            raise Exception(f"Ошибка при создании ассистента через Yandex AI Studio: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error creating assistant: {e}", exc_info=True)
            raise Exception(f"Неожиданная ошибка при создании ассистента: {str(e)}")
    
    def send_message(self, assistant_id: str, message: str, history: List[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Send message to assistant
        
        Args:
            assistant_id: Assistant identifier
            message: User message
            history: Optional chat history in format [{"role": "user|assistant", "content": "..."}, ...]
        
        Returns:
            Dictionary with response:
            {
                "answer": "Assistant response text",
                "sources": [{"file": "...", "page": ..., "content": "..."}, ...]
            }
        """
        if not self.auth_token or not self.folder_id:
            raise ValueError(
                "YANDEX_API_KEY/YANDEX_IAM_TOKEN and YANDEX_FOLDER_ID must be set"
            )
        
        # TODO: Verify actual API endpoint and message format
        # This is a placeholder based on typical chat API patterns
        url = f"{self.base_url}/foundationModels/v1/assistants/{assistant_id}/chat"
        
        # Build messages list
        messages = []
        
        # Add history if provided
        if history:
            for msg in history:
                messages.append({
                    "role": msg.get("role", "user"),
                    "text": msg.get("content") or msg.get("text", "")
                })
        
        # Add current message
        messages.append({
            "role": "user",
            "text": message
        })
        
        payload = {
            "messages": messages
        }
        
        try:
            logger.debug(f"Sending message to assistant {assistant_id}")
            response = requests.post(url, json=payload, headers=self._get_headers(), timeout=60)
            response.raise_for_status()
            
            result = response.json()
            
            # Parse response
            # Actual response format should be verified with documentation
            # Expected format: {"response": {"text": "...", "sources": [...]}}
            response_data = result.get("response") or result.get("result") or result
            
            answer = response_data.get("text") or response_data.get("content") or response_data.get("answer") or ""
            
            # Extract sources if available
            sources = []
            sources_data = response_data.get("sources") or response_data.get("citations") or []
            
            for source in sources_data:
                sources.append({
                    "file": source.get("file") or source.get("filename") or "unknown",
                    "page": source.get("page"),
                    "start_line": source.get("start_line") or source.get("line"),
                    "end_line": source.get("end_line"),
                    "content": source.get("content") or source.get("text") or ""
                })
            
            return {
                "answer": answer,
                "sources": sources
            }
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending message via Yandex AI Studio API: {e}", exc_info=True)
            raise Exception(f"Ошибка при отправке сообщения через Yandex AI Studio: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error sending message: {e}", exc_info=True)
            raise Exception(f"Неожиданная ошибка при отправке сообщения: {str(e)}")
    
    def get_assistant(self, assistant_id: str) -> Dict[str, Any]:
        """
        Get assistant configuration
        
        Args:
            assistant_id: Assistant identifier
        
        Returns:
            Dictionary with assistant configuration
        """
        if not self.auth_token or not self.folder_id:
            raise ValueError(
                "YANDEX_API_KEY/YANDEX_IAM_TOKEN and YANDEX_FOLDER_ID must be set"
            )
        
        # TODO: Verify actual API endpoint
        url = f"{self.base_url}/foundationModels/v1/assistants/{assistant_id}"
        
        try:
            logger.debug(f"Getting assistant {assistant_id}")
            response = requests.get(url, headers=self._get_headers(), timeout=30)
            response.raise_for_status()
            
            result = response.json()
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting assistant via Yandex AI Studio API: {e}", exc_info=True)
            raise Exception(f"Ошибка при получении ассистента через Yandex AI Studio: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error getting assistant: {e}", exc_info=True)
            raise Exception(f"Неожиданная ошибка при получении ассистента: {str(e)}")
    
    def delete_assistant(self, assistant_id: str) -> None:
        """
        Delete assistant
        
        Args:
            assistant_id: Assistant identifier to delete
        """
        if not self.auth_token or not self.folder_id:
            raise ValueError(
                "YANDEX_API_KEY/YANDEX_IAM_TOKEN and YANDEX_FOLDER_ID must be set"
            )
        
        # TODO: Verify actual API endpoint
        url = f"{self.base_url}/foundationModels/v1/assistants/{assistant_id}"
        
        try:
            logger.info(f"Deleting assistant {assistant_id}")
            response = requests.delete(url, headers=self._get_headers(), timeout=30)
            response.raise_for_status()
            
            logger.info(f"✅ Deleted assistant {assistant_id}")
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error deleting assistant via Yandex AI Studio API: {e}", exc_info=True)
            raise Exception(f"Ошибка при удалении ассистента через Yandex AI Studio: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error deleting assistant: {e}", exc_info=True)
            raise Exception(f"Неожиданная ошибка при удалении ассистента: {str(e)}")
    
    def get_assistant_id(self, case_id: str, db_session=None) -> Optional[str]:
        """
        Get assistant_id for case from database
        
        Args:
            case_id: Case identifier
            db_session: Database session (optional, if not provided will try to get from context)
        
        Returns:
            assistant_id if found, None otherwise
        """
        if not db_session:
            # Try to get from database if session not provided
            try:
                from app.utils.database import SessionLocal
                db = SessionLocal()
                try:
                    from app.models.case import Case
                    case = db.query(Case).filter(Case.id == case_id).first()
                    return case.yandex_assistant_id if case else None
                finally:
                    db.close()
            except Exception as e:
                logger.warning(f"Could not get assistant_id from database: {e}")
                return None
        
        try:
            from app.models.case import Case
            case = db_session.query(Case).filter(Case.id == case_id).first()
            return case.yandex_assistant_id if case else None
        except Exception as e:
            logger.warning(f"Could not get assistant_id from database: {e}")
            return None
    
    def is_available(self) -> bool:
        """Проверяет, доступен ли сервис ассистентов"""
        return bool(self.auth_token and self.folder_id)

