"""持久对话响应契约。"""

from app.contracts.base import ContractModel


class MessageOut(ContractModel):
    id: str
    role: str
    content: dict
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
