"""Translate Pydantic validation schemas to the strict structured-output subset."""


def strict_schema(model):
    schema = model.model_json_schema()

    def visit(value):
        if isinstance(value, list):
            return [visit(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {
            key: visit(item)
            for key, item in value.items()
            if key not in ("default", "discriminator")
        }
        if "oneOf" in result:
            result["anyOf"] = result.pop("oneOf")
        if result.get("type") == "object" and "properties" in result:
            result["required"] = list(result["properties"])
            result["additionalProperties"] = False
        return result

    return visit(schema)
