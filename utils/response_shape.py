"""Bounded structural samples, never response values or a server schema claim."""
import json
import re

FIELD_NAME = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]{0,47}\Z")
OPAQUE_HEX = re.compile(r"[0-9a-fA-F]{16,}\Z")


def response_shape(value, *, depth=0, max_depth=6, max_properties=60, sample_items=3):
    if value is None:
        return {"type": "null"}
    if type(value) is bool:
        return {"type": "boolean"}
    if type(value) is int:
        return {"type": "integer"}
    if type(value) is float:
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if depth >= max_depth:
        return {"type": "object" if isinstance(value, dict) else "array", "truncated": True}
    options = dict(depth=depth + 1, max_depth=max_depth,
                   max_properties=max_properties, sample_items=sample_items)
    if isinstance(value, list):
        shapes = {
            json.dumps(response_shape(item, **options), sort_keys=True)
            for item in value[:sample_items]
        }
        return {
            "type": "array", "observed_length": len(value),
            "sampled_item_shapes": [json.loads(shape) for shape in sorted(shapes)],
            "items_sampled": min(len(value), sample_items),
        }
    if isinstance(value, dict):
        properties = {}
        omitted = 0
        for key, child in value.items():
            safe = (isinstance(key, str) and FIELD_NAME.fullmatch(key)
                    and not OPAQUE_HEX.fullmatch(key)
                    and not (len(key) > 24 and any(c.isdigit() for c in key)))
            if not safe or len(properties) >= max_properties:
                omitted += 1
                continue
            properties[key] = response_shape(child, **options)
        return {"type": "object", "properties": properties,
                "omitted_dynamic_or_excess_keys": omitted}
    return {"type": "unsupported"}
