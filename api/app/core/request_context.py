"""Request-scoped correlation values carried through contextvars.

中间件在每个请求开始时写入 `request_id`（以及可选的实际操作者 `actor_id`），
业务代码通过 `record_event` 自动读取，无需逐层透传参数——
这是补齐大量审计调用点时改动量最小的关键。

后台任务没有 HTTP 请求，但同样需要一条能把「日志行—审计行—被处理的实体」
串起来的线索。`correlation()` 让 worker 用被处理单元自身的 ID 作为关联 ID，
于是 worker 产生的审计行也带上 `request_id`，与日志行一一对应。

因此约定：`request_id` 的语义是**一次可追责的处理单元**，HTTP 请求是它最常见的
形态，但后台任务也算。字段名沿用 `request_id` 是为了让两层日志共用同一个查询入口。
"""

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator


request_id_var: ContextVar[uuid.UUID | None] = ContextVar("request_id", default=None)
actor_id_var: ContextVar[uuid.UUID | None] = ContextVar("actor_id", default=None)


def current_request_id() -> uuid.UUID | None:
    return request_id_var.get()


def current_actor_id() -> uuid.UUID | None:
    return actor_id_var.get()


@contextmanager
def correlation(request_id: uuid.UUID, actor_id: uuid.UUID | None = None) -> Iterator[uuid.UUID]:
    """在代码块内绑定关联 ID，退出时恢复原值。

    后台任务用被处理单元（索引任务、上传会话、摘要运行）的 ID 作为关联 ID，
    这样该单元内的日志行与它产生的审计行共享同一个可检索的标识。
    退出时 reset 而非清空，嵌套使用时不会污染外层上下文。
    """
    request_token = request_id_var.set(request_id)
    actor_token = actor_id_var.set(actor_id) if actor_id is not None else None
    try:
        yield request_id
    finally:
        request_id_var.reset(request_token)
        if actor_token is not None:
            actor_id_var.reset(actor_token)
