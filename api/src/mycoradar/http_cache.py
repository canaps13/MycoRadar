"""Bounded If-None-Match parsing for weak public-catalogue representation validators."""

import hashlib
import re

ENTITY_TAG = re.compile(r'(?:W/)?"[!\x23-\x7e\x80-\xff]*"')
CACHE_POLICY = "private, no-cache"


def etag(body: bytes) -> str:
    return f'W/"{hashlib.sha256(body).hexdigest()}"'


def not_modified(header: str | None, current: str) -> bool:
    if header is None or len(header) > 4096:
        return False
    value = header.strip(" \t")
    if value == "*":
        return True
    tags: list[str] = []
    position = 0
    while position < len(value):
        match = ENTITY_TAG.match(value, position)
        if match is None or len(tags) >= 32:
            return False
        tags.append(match.group().removeprefix("W/"))
        position = match.end()
        while position < len(value) and value[position] in " \t":
            position += 1
        if position == len(value):
            return current.removeprefix("W/") in tags
        if value[position] != ",":
            return False
        position += 1
        while position < len(value) and value[position] in " \t":
            position += 1
    return False
