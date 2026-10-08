"""契约与边界门禁（静态）。

这是"从源头截断"的自动化关卡：把"哪些端点有响应契约""tool 能发哪些字段"
"用户所属实体的查询是否带归属过滤"变成构建前必须通过的断言。红灯即视为回归。

用法（容器内，与其它 verify 脚本一致）：
  python -m scripts.contract_check --static            # 校验（默认）
  python -m scripts.contract_check --update-inventory  # 重生成端点清单（产出可评审 diff）
  python -m scripts.contract_check --update-goldens    # 重生成 tool 信封快照

退出码非 0 表示存在违规。
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import pathlib
import sys
import typing

from fastapi.routing import APIRoute
from starlette.responses import Response, StreamingResponse

from app.contracts.base import COORDINATE_ALLOW, COORDINATE_FIELDS, is_api_denied
from app.assistant import tool_contract
from app.main import app


APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"
CONTRACTS_DIR = APP_DIR / "contracts"
GOLDENS_DIR = CONTRACTS_DIR / "goldens"
INVENTORY_PATH = CONTRACTS_DIR / "inventory.json"
OWNERSHIP_ALLOWLIST_PATH = CONTRACTS_DIR / "ownership_allowlist.json"

# 走 Response / StreamingResponse 的端点（不适用 response_model）。
ALLOWLISTED_PATHS = {
    "/health/live", "/health/ready", "/health/embedding",
    "/v1/notes/export", "/v1/notes/{note_id}/export", "/v1/notebooks/{notebook_id}/export",
    "/v1/notes/{note_id}/file", "/v1/files/{storage_key}",
    "/v1/assistant/conversations/{conversation_id}/messages/stream",
}

# 用户所属实体：这些实体的 select 必须带归属过滤，除非函数在 allowlist 内。
OWNED_ENTITIES = {
    "Note", "Notebook", "Tag", "NoteReminder",
    "AssistantConversation", "AssistantMessage", "AssistantOperation", "AssistantTrace", "FileUploadSession",
}
# 已退役的重复实现：不得再次出现。
RETIRED_SYMBOLS = {"current_note", "owned", "_owned_session", "require_conversation", "require_message"}


def _iter_python_files() -> list[pathlib.Path]:
    return sorted(path for path in APP_DIR.rglob("*.py") if "__pycache__" not in path.parts)


def _return_annotation(endpoint) -> typing.Any:
    try:
        hints = typing.get_type_hints(endpoint)
    except Exception:
        return inspect.signature(endpoint).return_annotation
    return hints.get("return", inspect.signature(endpoint).return_annotation)


def _is_contract_model(model: typing.Any) -> bool:
    from pydantic import BaseModel
    return isinstance(model, type) and issubclass(model, BaseModel)


def _contract_model_name(model: typing.Any) -> str | None:
    """返回契约模型名；支持裸模型与 list[模型]。裸 dict/list 不算契约。"""
    if _is_contract_model(model):
        return f"{model.__module__.rsplit('.', 1)[-1]}.{model.__name__}"
    if typing.get_origin(model) in (list,):
        args = typing.get_args(model)
        if len(args) == 1 and _is_contract_model(args[0]):
            inner = args[0]
            return f"{inner.__module__.rsplit('.', 1)[-1]}.{inner.__name__}"
    return None


def _classify(route: APIRoute) -> tuple[str, str | None]:
    """返回 (kind, model_name)；kind ∈ declared / allowlisted / unmodeled。

    只有真正的 Pydantic 契约模型（含 list[模型]）才算 declared。裸 `-> dict` / `-> list`
    会被 FastAPI 推断成 response_model=dict/list，那不是契约，仍视为 unmodeled。
    """
    model_name = _contract_model_name(route.response_model)
    if model_name is not None:
        return "declared", model_name
    annotation = _return_annotation(route.endpoint)
    if annotation in (Response, StreamingResponse, None, type(None)) or route.path in ALLOWLISTED_PATHS:
        return "allowlisted", None
    return "unmodeled", None


def _route_key(route: APIRoute) -> str:
    methods = sorted(m for m in route.methods if m not in {"HEAD", "OPTIONS"})
    return f"{','.join(methods)} {route.path}"


def _all_api_routes() -> list[APIRoute]:
    """收集全部 API 路由。

    FastAPI 0.142 把 include_router 的结果包成 _IncludedRouter（非 APIRoute），
    真正的路由在其 original_router.routes 里，需展开。
    """
    routes: list[APIRoute] = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            routes.append(route)
            continue
        original = getattr(route, "original_router", None)
        if original is not None:
            routes.extend(item for item in original.routes if isinstance(item, APIRoute))
    return routes


def _collect_models() -> dict[str, type]:
    """收集 app.contracts 下所有 BaseModel 子类，用于字段拒绝清单检查。"""
    from pydantic import BaseModel
    models: dict[str, type] = {}
    for path in CONTRACTS_DIR.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        module = ".".join(path.relative_to(APP_DIR.parent).with_suffix("").parts)
        try:
            mod = __import__(module, fromlist=["*"])
        except Exception:
            continue
        for name, obj in vars(mod).items():
            if isinstance(obj, type) and issubclass(obj, BaseModel) and obj.__module__ == module:
                models[f"{path.stem}.{name}"] = obj
    return models


def _model_fields(model: type) -> list[str]:
    from pydantic import BaseModel
    if isinstance(model, type) and issubclass(model, BaseModel):
        return list(model.model_fields)
    return []


def check_endpoints(failures: list[str]) -> list[str]:
    routes = _all_api_routes()
    declared, allowlisted, unmodeled = [], [], []
    for route in routes:
        kind, model_name = _classify(route)
        if kind == "declared":
            declared.append((_route_key(route), model_name))
        elif kind == "allowlisted":
            allowlisted.append(_route_key(route))
        else:
            unmodeled.append(_route_key(route))
    return sorted(declared), sorted(allowlisted), sorted(unmodeled)


def check_denylist(declared: list[tuple[str, str]], failures: list[str]) -> None:
    models = _collect_models()
    for _route_key_str, model_name in declared:
        model = models.get(model_name)
        if model is None:
            continue
        module = model_name.split(".", 1)[0]
        for field in _model_fields(model):
            if is_api_denied(field):
                failures.append(f"响应模型 {model_name} 暴露被禁字段 {field!r}")
            if field in COORDINATE_FIELDS and (module, model_name.split(".", 1)[1]) not in COORDINATE_ALLOW:
                failures.append(
                    f"响应模型 {model_name} 声明坐标字段 {field!r}，但不在允许集 {sorted(COORDINATE_ALLOW)}"
                )


def check_tool_envelopes(failures: list[str], *, update: bool) -> None:
    try:
        tool_contract.assert_envelopes_clean()
    except AssertionError as exc:
        failures.append(str(exc))
        return
    GOLDENS_DIR.mkdir(parents=True, exist_ok=True)
    for kind, envelope in tool_contract.ENVELOPES.items():
        snapshot = {
            "keys": sorted(envelope["keys"]),
            "nested": {field: sorted(tool_contract.NESTED_ENVELOPES[nk]) for field, nk in (envelope.get("nested") or {}).items()},
        }
        path = GOLDENS_DIR / f"tool_{kind}.json"
        if update:
            path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            continue
        if not path.exists():
            failures.append(f"缺少 tool 信封 golden：{path.name}（运行 --update-goldens 生成）")
            continue
        expected = json.loads(path.read_text(encoding="utf-8"))
        if expected != snapshot:
            failures.append(f"tool 信封 {kind} 与 golden 不一致：{snapshot} != {expected}")


def _func_name(node: ast.AST, stack: list[str]) -> str:
    return stack[-1] if stack else "<module>"


def check_ownership(failures: list[str]) -> None:
    allowlist = set()
    if OWNERSHIP_ALLOWLIST_PATH.exists():
        data = json.loads(OWNERSHIP_ALLOWLIST_PATH.read_text(encoding="utf-8"))
        allowlist = {(item["file"], item["function"]) for item in data.get("allowed", [])}

    for path in _iter_python_files():
        rel = str(path.relative_to(APP_DIR))
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        stack: list[str] = []

        def walk(node: ast.AST, stack: list[str]) -> None:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_name = node.name
                selects_owned = _selects_owned(node)
                if selects_owned and not _has_user_id_predicate(node):
                    if (rel, func_name) not in allowlist:
                        failures.append(
                            f"归属查询缺少 user_id 过滤：{rel}:{func_name}（如确有例外，请登记到 ownership_allowlist.json）"
                        )
                if func_name in RETIRED_SYMBOLS:
                    failures.append(f"已退役的重复实现仍存在：{rel}:{func_name}")
                for child in ast.iter_child_nodes(node):
                    walk(child, stack + [func_name])
                return
            for child in ast.iter_child_nodes(node):
                walk(child, stack)

        walk(tree, stack)


def _selects_owned(func: ast.AST) -> bool:
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "select":
            for arg in node.args:
                if isinstance(arg, ast.Name) and arg.id in OWNED_ENTITIES:
                    return True
    return False


def _has_user_id_predicate(func: ast.AST) -> bool:
    for node in ast.walk(func):
        if isinstance(node, ast.Attribute) and node.attr == "user_id":
            return True
    return False


def write_inventory(declared, allowlisted, unmodeled) -> None:
    payload = {
        "declared": [{"route": r, "model": m} for r, m in declared],
        "allowlisted": allowlisted,
        "unmodeled": unmodeled,
        "note": "未建模端点（迁移到 response_model 后逐项移出）。新增端点若未建模且不在此清单，门禁失败。",
    }
    INVENTORY_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--static", action="store_true", default=True)
    parser.add_argument("--update-inventory", action="store_true")
    parser.add_argument("--update-goldens", action="store_true")
    args = parser.parse_args()

    failures: list[str] = []
    declared, allowlisted, unmodeled = check_endpoints(failures)

    if args.update_inventory:
        write_inventory(declared, allowlisted, unmodeled)
        print(f"inventory 已更新：declared={len(declared)} allowlisted={len(allowlisted)} unmodeled={len(unmodeled)}")
        return 0

    if args.update_goldens:
        check_tool_envelopes(failures, update=True)
        print("tool 信封 golden 已更新")
        return 0

    # 端点覆盖：未建模端点必须在清单内，否则视为"新增无契约端点"。
    if not INVENTORY_PATH.exists():
        failures.append("缺少 inventory.json（运行 --update-inventory 生成）")
    else:
        known = set(json.loads(INVENTORY_PATH.read_text(encoding="utf-8")).get("unmodeled", []))
        new_unmodeled = [route for route in unmodeled if route not in known]
        if new_unmodeled:
            failures.append("新增未建模端点（请补 response_model 或先评审登记）：\n  " + "\n  ".join(new_unmodeled))

    check_denylist(declared, failures)
    check_tool_envelopes(failures, update=False)
    check_ownership(failures)

    if failures:
        print("契约门禁未通过：\n", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print(f"契约门禁通过：declared={len(declared)} allowlisted={len(allowlisted)} unmodeled={len(unmodeled)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
