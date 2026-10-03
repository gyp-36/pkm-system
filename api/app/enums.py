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


class AuditEntityType(IntEnum):
    ACCOUNT = 1
    SESSION = 2
    NOTE = 3
    NOTEBOOK = 4
    TAG = 5


class ModelProvider(IntEnum):
    DEEPSEEK = 1


class AssistantMessageRole(IntEnum):
    USER = 1
    ASSISTANT = 2
