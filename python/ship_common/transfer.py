from __future__ import annotations

import json
from typing import Any, Dict
from urllib import request


def post_json(url: str, payload: Dict[str, Any], timeout: float = 10.0) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    http_request = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with request.urlopen(http_request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    if not body:
        return {}
    return json.loads(body)
