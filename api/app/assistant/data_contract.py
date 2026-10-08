"""Recursive, non-coercing data schemas for model and user projections."""


def validate_shape(value, schema, *, project=False, path="payload"):
    if isinstance(schema, dict):
        if not isinstance(value, dict):
            raise KeyError(f"invalid object at {path}")
        if not project and set(value) - set(schema):
            raise KeyError(f"unregistered fields at {path}")
        return {key: validate_shape(item, schema[key], project=project, path=f"{path}.{key}")
                for key, item in value.items() if key in schema}
    if isinstance(schema, list):
        if not isinstance(value, list):
            raise KeyError(f"invalid list at {path}")
        return [validate_shape(item, schema[0], project=project, path=path + "[]") for item in value]
    types = schema if isinstance(schema, tuple) else (schema,)
    # bool must never be silently accepted as an integer.
    if type(value) not in types:
        raise KeyError(f"invalid scalar at {path}")
    return value
