"""字段边界常量与契约基类。"""

from app.contracts.base import (
    API_DENYLIST,
    API_DENY_SUFFIXES,
    COORDINATE_ALLOW,
    COORDINATE_FIELDS,
    MODEL_DENYLIST,
    ContractModel,
    is_api_denied,
)

__all__ = [
    "API_DENYLIST",
    "API_DENY_SUFFIXES",
    "COORDINATE_ALLOW",
    "COORDINATE_FIELDS",
    "MODEL_DENYLIST",
    "ContractModel",
    "is_api_denied",
]
