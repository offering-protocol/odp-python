"""Decode mixed Directory results without treating unknown types as Services."""

from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import urlsplit

from pydantic import JsonValue, TypeAdapter

from offering_protocol.core import (
    derive_service_origin,
    is_local_resource_identifier,
    parse_agent_service_document,
)
from offering_protocol.directory.models import (
    CollectionResult,
    DirectoryIssue,
    DirectoryResult,
    SearchResponse,
    ServiceResult,
    UnknownResult,
)
from offering_protocol.directory.sources import read_source, validate_imported_service

_OBJECT = TypeAdapter(dict[str, JsonValue])


def parse_search_response(body: bytes) -> SearchResponse:
    raw = _OBJECT.validate_json(body)
    candidates = raw.get("items")
    if not isinstance(candidates, list) or len(candidates) > 100:
        raise ValueError("items must be an array of at most 100 results")
    items: list[DirectoryResult] = []
    issues: list[DirectoryIssue] = []
    for index, candidate in enumerate(candidates):
        try:
            items.append(_result(candidate))
        except ValueError as error:
            issues.append(DirectoryIssue(index=index, message=str(error)))
    response = SearchResponse.model_validate({**raw, "items": items, "issues": issues})
    if response.next is not None and not response.next.strip():
        raise ValueError("Directory continuation is empty")
    if response.facets is not None and any(
        facet.value.name.value != "tap" for facet in response.facets.trust
    ):
        raise ValueError("Directory trust facets are invalid")
    return response


def _result(value: JsonValue) -> DirectoryResult:
    raw = _OBJECT.validate_python(value)
    kind = _text(raw, "type", 128)
    if kind not in {"service", "collection"}:
        return UnknownResult(type=kind, raw=raw)
    _timestamp(raw)
    service = _OBJECT.validate_python(raw.get("service"))
    _text(service, "service_id", 128)
    _origin(service)
    _timestamp(service)
    source = read_source(service.get("source"))
    for name in (
        "branding",
        "http",
        "mcp",
        "odp_version",
        "payment_origins",
        "search_capabilities",
    ):
        service.pop(name, None)
    if source.type == "odp":
        _native_service(service)
    else:
        validate_imported_service(service)
    raw["service"] = service
    return _finish_result(raw, kind)


def _native_service(service: dict[str, JsonValue]) -> None:
    candidate = dict(service)
    candidate.pop("source")
    document = parse_agent_service_document(
        json.dumps({**candidate, "odp_version": "1.0", "http": {"endpoint_base": "/"}})
    )
    service["operations"] = [operation.to_dict() for operation in document.operations]
    if document.protocols is None:
        service.pop("protocols", None)
    else:
        service["protocols"] = document.protocols.to_dict()


def _finish_result(raw: dict[str, JsonValue], kind: str) -> DirectoryResult:
    if kind == "service":
        if raw.get("publisher") is not None:
            publisher = _OBJECT.validate_python(raw["publisher"])
            _text(publisher, "publisher_id", 128)
            _text(publisher, "name", 128)
            website = urlsplit(_text(publisher, "website_url", 512))
            if website.scheme != "https" or not website.hostname or website.username is not None:
                raise ValueError("Publisher website must be an HTTPS URL without credentials")
        return ServiceResult.model_validate(raw)
    collection = _OBJECT.validate_python(raw.get("collection"))
    if not is_local_resource_identifier(_text(collection, "id", 128)):
        raise ValueError("collection.id must be a local resource identifier")
    _text(collection, "name", 128)
    if "description" in collection:
        description = collection["description"]
        if not isinstance(description, str) or len(description) > 1024:
            raise ValueError("collection.description must be a string of at most 1024 characters")
    return CollectionResult.model_validate(raw)


def _origin(value: dict[str, JsonValue]) -> None:
    origin = _text(value, "service_origin", 2048)
    if not origin.startswith("https://") or derive_service_origin(origin) != origin:
        raise ValueError("service_origin must be a canonical HTTPS origin")


def _timestamp(value: dict[str, JsonValue]) -> None:
    timestamp = _text(value, "indexed_at", 64)
    if datetime.fromisoformat(timestamp.replace("Z", "+00:00")).tzinfo is None:
        raise ValueError("indexed_at must contain a timezone")


def _text(value: dict[str, JsonValue], field: str, maximum: int) -> str:
    text = value.get(field)
    if not isinstance(text, str) or not text.strip() or len(text) > maximum:
        raise ValueError(f"{field} must be a nonempty string of at most {maximum} characters")
    return text
