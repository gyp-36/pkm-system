"""持久对话响应契约。"""

from app.contracts.base import ContractModel
from app.contracts.assistant import AnswerOut


class UserContentOut(ContractModel):
    text: str


class LegacySearchItemOut(ContractModel):
    title: str
    snippet: str


class LegacySearchContentOut(ContractModel):
    items: list[LegacySearchItemOut]


class MessageOut(ContractModel):
    id: str
    role: str
    content: UserContentOut | AnswerOut | LegacySearchContentOut
    created_at: str


class ConversationOut(ContractModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class ConversationListOut(ContractModel):
    items: list[ConversationOut]


class ConversationWithMessagesOut(ConversationOut):
    messages: list[MessageOut]
