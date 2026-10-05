"""Stable database codes for finite M1 values; public API uses lowercase names."""

from enum import IntEnum


class NoteIndexStatus(IntEnum):
    PENDING = 1
    READY = 2
    ERROR = 3


class ChunkSource(IntEnum):
    TITLE = 1
    BODY = 2


class IndexJobStatus(IntEnum):
    PENDING = 1
    PROCESSING = 2
    DONE = 3
    STALE = 4


class AuditActor(IntEnum):
    USER = 1
    SYSTEM = 2


class AuditAction(IntEnum):
    REGISTER = 1
    LOGIN = 2
    LOGOUT = 3
    CREATE = 4
    UPDATE = 5
    RENAME = 6
    DELETE = 7
    RESTORE = 8
    TEST = 9


class AuditOutcome(IntEnum):
    """审计事件的执行结果。旧数据该字段为空，语义上等同 SUCCESS。"""

    SUCCESS = 1
    FAILED = 2


class AuditEntityType(IntEnum):
    ACCOUNT = 1
    SESSION = 2
    NOTE = 3
    NOTEBOOK = 4
    TAG = 5
    REMINDER = 6
    TEMPLATE = 7
    CONVERSATION = 8
    MODEL_CONNECTION = 9
    UPLOAD_SESSION = 10
    LINK_DRAFT = 11
    DIGEST = 12
    ASSISTANT_MESSAGE = 13
    # 中间件为被拒请求补记的失败事件，entity_id 复用 request_id
    REQUEST = 14


class ModelProvider(IntEnum):
    DEEPSEEK = 1


class AssistantMessageRole(IntEnum):
    USER = 1
    ASSISTANT = 2
