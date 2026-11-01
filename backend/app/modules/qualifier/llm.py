"""The model behind the Qualifier: the same providers as the staff assistant, or the scripted
fake (tests and local demos; the settings refuse it in production)."""

from app.core.config import Settings
from app.modules.assistant import api as assistant_api
from app.modules.assistant.api import ChatModel
from app.modules.qualifier.fake import FakeQualifierModel


def model_for(settings: Settings) -> ChatModel:
    if settings.ai_provider == "fake":
        return FakeQualifierModel()
    if settings.ai_provider == "deepseek":
        return assistant_api.chat_model_for(settings, "deepseek")
    return assistant_api.chat_model_for(settings, "anthropic")
