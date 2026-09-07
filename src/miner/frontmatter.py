"""Lossless body splitting and safe, bounded YAML tree extraction."""

import json
import re

import yaml


class WorkflowLoader(getattr(yaml, "CSafeLoader", yaml.SafeLoader)):
    pass


# YAML 1.1 turns the GitHub key `on` into True. Only true/false are booleans.
# Dates remain strings, avoiding implicit date conversion and JSON type loss.
WorkflowLoader.yaml_implicit_resolvers = {
    key: [(tag, pattern) for tag, pattern in rules
          if tag not in {"tag:yaml.org,2002:bool", "tag:yaml.org,2002:timestamp"}]
    for key, rules in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
WorkflowLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$", re.IGNORECASE), list("tTfF")
)


def mapping(loader, node):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str):
            raise ValueError("las claves YAML deben ser strings")
        if key in result:
            raise ValueError(f"clave YAML duplicada: {key}")
        result[key] = loader.construct_object(value_node)
    return result


WorkflowLoader.add_constructor("tag:yaml.org,2002:map", mapping)


def split_markdown(text):
    """Return raw YAML, exact body and presence of a closed frontmatter."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].lstrip("\ufeff").rstrip("\r\n \t") != "---":
        return None, text, "missing"
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r\n \t") in {"---", "..."}:
            return "".join(lines[1:index]), "".join(lines[index + 1:]), "present"
    return "".join(lines[1:]), text, "unclosed"


def parse_nodes(raw, workflow_id):
    """Represent maps/lists/scalars as a relational tree with JSON pointers."""
    value = yaml.load(raw, Loader=WorkflowLoader)
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("el frontmatter debe ser un mapping YAML")
    rows = []

    def visit(item, pointer, parent, key, position, ancestors, depth):
        if depth > 64 or len(rows) >= 100_000:
            raise ValueError("frontmatter excede el límite de profundidad/nodos")
        node_id = workflow_id + ":" + pointer
        if isinstance(item, (dict, list)):
            if id(item) in ancestors:
                raise ValueError("alias YAML cíclico")
            kind = "mapping" if isinstance(item, dict) else "sequence"
            scalar = None
        else:
            kind = {type(None): "null", str: "string", bool: "boolean",
                    int: "integer", float: "number"}.get(type(item))
            if kind is None:
                raise ValueError(f"tipo YAML no soportado: {type(item).__name__}")
            scalar = json.dumps(item, ensure_ascii=False, allow_nan=False)
        rows.append(dict(node_id=node_id, workflow_id=workflow_id,
                         parent_node_id=parent, pointer=pointer, key=key,
                         position=position, kind=kind, value_json=scalar))
        if isinstance(item, (dict, list)):
            children = item.items() if isinstance(item, dict) else enumerate(item)
            for offset, (child_key, child) in enumerate(children):
                escaped = str(child_key).replace("~", "~0").replace("/", "~1")
                visit(child, pointer + "/" + escaped, node_id,
                      child_key if isinstance(item, dict) else None,
                      offset, ancestors | {id(item)}, depth + 1)

    visit(value, "", None, None, 0, set(), 0)
    return rows
