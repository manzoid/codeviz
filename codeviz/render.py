"""Render an OPT trace dict into a self-contained HTML page."""
from __future__ import annotations

import json
import os

_TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "viewer_template.html")


def render_html(data: dict, title: str, lang: str = "python") -> str:
    """Embed ``data`` (with a ``lang`` hint) into the viewer template."""
    with open(_TEMPLATE, encoding="utf-8") as f:
        tmpl = f.read()
    payload = dict(data)
    payload.setdefault("lang", lang)
    blob = json.dumps(payload)
    # guard against an accidental </script> inside string literals in the trace
    blob = blob.replace("</", "<\\/")
    return tmpl.replace("__TRACE_JSON__", blob).replace("__TITLE__", title)
