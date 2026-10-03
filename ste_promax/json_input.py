"""Strict JSON ingestion without silently changing displayed numeric evidence."""
from decimal import Decimal, InvalidOperation
import json
import math


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key!r}.")
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f"JSON constant {value!r} is not a finite JSON number.")


def loads_json(text: str):
    """Keep ordinary JSON types, but reject decimal tokens that would change value.

    Decimal is only an ingestion check, not a new public chart numeric type.
    Native floats must round-trip through their displayed decimal spelling to the
    supplied value. Formatting (1e2 versus 100.0) may differ; source bytes persist.
    """
    try:
        value = json.loads(text, object_pairs_hook=_object,
                           parse_float=Decimal, parse_constant=_constant)
    except (RecursionError, InvalidOperation) as error:
        raise ValueError("JSON nesting or numeric exponent exceeds the supported limits.") from error

    def convert(item, location, depth):
        if depth > 64:
            raise ValueError(f"{location}: JSON nesting exceeds 64 levels.")
        if isinstance(item, Decimal):
            number = float(item)
            if not math.isfinite(number) or Decimal(str(number)) != item:
                raise ValueError(
                    f"{location}: JSON number {item} cannot be represented without changing its decimal value; "
                    "use a supported precision/range or retain it as explicitly labeled text."
                )
            return number
        if isinstance(item, list):
            return [convert(child, f"{location}[{index}]", depth + 1) for index, child in enumerate(item)]
        if isinstance(item, dict):
            return {key: convert(child, f"{location}.{key}", depth + 1) for key, child in item.items()}
        return item

    return convert(value, "input", 0)
