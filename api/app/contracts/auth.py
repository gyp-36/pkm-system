"""账户响应契约。"""

from app.contracts.base import ContractModel


class AccountOut(ContractModel):
    id: str
    email: str
