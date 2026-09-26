from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import JsonValue

from helpers import QueueTransport, response
from offering_protocol.directory import (
    CollectionResult,
    DirectoryClient,
    DirectoryError,
    DirectoryService,
    Environment,
    IterationOptions,
    ResourceSearchRequest,
    SearchRequest,
    ServiceFilters,
    ServiceResult,
    SuggestionRequest,
    UnknownResult,
)
from offering_protocol.directory.transport import HttpRequest, HttpResponse


def service() -> dict[str, JsonValue]:
    return {
        "service_id": "parent",
        "source": {
            "type": "odp",
            "url": "https://api.example.com/.well-known/odp",
            "x402_discovery": False,
        },
        "service_origin": "https://api.example.com",
        "indexed_at": "2026-09-18T11:00:00Z",
        "name": "Data",
        "description": "Data services.",
        "language": "en",
        "localizations": ["en"],
        "operations": [
            {"name": "get-offering", "authentication": "not-required"},
            {"name": "list-offerings", "authentication": "not-required"},
            {"name": "future-operation", "authentication": "not-required"},
        ],
        "protocols": {"trust": [{"name": "tap"}, {"name": "future"}]},
    }


def item(kind: str = "collection") -> dict[str, JsonValue]:
    raw: dict[str, JsonValue] = {
        "type": kind,
        "service": service(),
        "indexed_at": "2026-09-18T12:00:00Z",
    }
    if kind == "collection":
        raw["collection"] = {
            "id": "Weather",
            "name": "Weather forecasts",
            "description": "Forecasts.",
        }
    return raw


def transport_for(body: object) -> QueueTransport:
    return QueueTransport(response(json.dumps(body), content_type="application/json"))


@pytest.mark.asyncio
async def test_mixed_results_metadata_unknown_types_and_requests() -> None:
    first = item("service")
    first["publisher"] = {
        "publisher_id": "platform",
        "website_url": "https://platform.example/catalog",
        "name": "Platform",
        "extra": True,
    }
    first["extra"] = True
    future: dict[str, JsonValue] = {"type": "future", "nested": {"value": 42}}
    transport = transport_for(
        {
            "items": [first, item(), future],
            "extra": 42,
            "facets": {"keywords": [{"value": "weather", "count": 12}]},
        }
    )
    async with DirectoryClient(Environment.SANDBOX, transport=transport) as client:
        result = await client.search(
            ResourceSearchRequest(query="weather", limit=10, types=["collection", "service"])
        )
    assert result.issues == []
    assert result.additional["extra"] == 42
    assert result.facets is not None and result.facets.keywords[0].count == 12
    first_result, second, third = result.items
    assert isinstance(first_result, ServiceResult)
    assert first_result.service.service_id == "parent"
    assert first_result.publisher is not None
    assert first_result.publisher.name == "Platform"
    assert first_result.publisher.additional["extra"] is True
    assert first_result.publisher.website_url == "https://platform.example/catalog"
    assert first_result.additional["extra"] is True
    assert len(first_result.service.operations) == 2
    assert first_result.service.protocols is not None
    assert len(first_result.service.protocols.trust) == 1
    assert isinstance(second, CollectionResult)
    assert second.collection.id == "Weather"
    assert second.indexed_at != second.service.indexed_at
    assert isinstance(third, UnknownResult)
    assert third.type == "future" and third.raw == future
    request = transport.requests[0]
    assert request.method == "POST"
    assert request.url == "https://sandbox.inflowpay.ai/v1/directory/search"
    assert json.loads(request.body) == {
        "query": "weather",
        "limit": 10,
        "types": ["collection", "service"],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["service", "collection"])
async def test_mixed_results_drop_unverified_execution_metadata(kind: str) -> None:
    parent = service()
    metadata: dict[str, JsonValue] = {
        "mcp": [{"type": "streamable-http", "url": "/mcp"}],
        "branding": {"icon": {"src": "/icon.png"}, "logo": {"src": "/logo.png"}},
        "payment_origins": ["https://payments.example"],
    }
    parent.update(metadata)
    raw = item(kind)
    raw["service"] = parent
    result = await DirectoryClient(transport=transport_for({"items": [raw]})).search(
        ResourceSearchRequest()
    )
    assert not result.issues
    entry = result.items[0]
    assert isinstance(entry, (ServiceResult, CollectionResult))
    for key in metadata:
        assert key not in entry.service.additional


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,value",
    [
        ("type", None),
        ("service/service_id", ""),
        ("service/service_origin", "http://api.example.com"),
        ("service/service_origin", "https://api.example.com/path"),
        ("service/operations", []),
        ("indexed_at", "yesterday"),
        ("indexed_at", "2026-09-18T00:00:00"),
        ("collection/id", "../bad"),
        ("collection/name", ""),
        ("collection/description", None),
        ("collection/description", "x" * 1025),
        ("service", None),
    ],
)
async def test_bad_known_items_do_not_discard_valid_items(path: str, value: JsonValue) -> None:
    invalid = item()
    parent = invalid
    parts = path.split("/")
    for part in parts[:-1]:
        child = parent[part]
        assert isinstance(child, dict)
        parent = child
    parent[parts[-1]] = value
    result = await DirectoryClient(transport=transport_for({"items": [invalid, item()]})).search(
        ResourceSearchRequest()
    )
    assert len(result.items) == 1
    assert len(result.issues) == 1 and result.issues[0].index == 0


@pytest.mark.asyncio
async def test_optional_members_and_unverified_metadata() -> None:
    first = item("service")
    parent = service()
    parent.pop("protocols")
    parent["http"] = {"endpoint_base": "https://untrusted.example/"}
    first["service"] = parent
    first["publisher"] = {
        "publisher_id": "platform",
        "website_url": "https://platform.example/catalog",
        "name": "Platform",
    }
    empty_description = item()
    empty_description["collection"] = {"id": "Weather", "name": "Weather", "description": ""}
    omitted_description = item()
    omitted_description["collection"] = {"id": "Weather", "name": "Weather"}
    result = await DirectoryClient(
        transport=transport_for(
            {"items": [first, item("service"), empty_description, omitted_description]}
        )
    ).search(ResourceSearchRequest())
    assert not result.issues
    parsed = result.items[0]
    assert isinstance(parsed, ServiceResult)
    assert "http" not in parsed.service.additional
    assert parsed.service.protocols is None
    assert parsed.publisher is not None and parsed.publisher.name == "Platform"
    parent = parsed.service.to_dict()
    parent.pop("service_id")
    assert DirectoryService.model_validate(parent).service_id is None


@pytest.mark.asyncio
async def test_publisher_omission_null_and_additional_fields() -> None:
    first = item("service")
    first["publisher"] = None
    first["available_through"] = {"service_id": "legacy"}
    first["future_metadata"] = {"arbitrary": True}
    result = await DirectoryClient(
        transport=transport_for({"items": [first, item("service")]})
    ).search(ResourceSearchRequest())
    assert not result.issues
    assert len(result.items) == 2
    parsed = result.items[0]
    assert isinstance(parsed, ServiceResult) and parsed.publisher is None
    assert parsed.additional["available_through"] == {"service_id": "legacy"}
    assert parsed.additional["future_metadata"] == {"arbitrary": True}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "website", ["http://platform.example", "https://user@platform.example", "https:///missing"]
)
async def test_publisher_website_validation(website: str) -> None:
    first = item("service")
    first["publisher"] = {"publisher_id": "gateway", "name": "Gateway", "website_url": website}
    result = await DirectoryClient(
        transport=transport_for({"items": [first, item("service")]})
    ).search(ResourceSearchRequest())
    assert len(result.issues) == 1 and len(result.items) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"items": None},
        {"items": [item()] * 101},
        {"items": [], "next": " "},
        {"items": [], "next": False},
        {"items": [], "facets": {"trust": [{"value": {"name": "mpp"}, "count": 1}]}},
    ],
)
async def test_invalid_envelopes(body: object) -> None:
    with pytest.raises(DirectoryError):
        await DirectoryClient(transport=transport_for(body)).search(ResourceSearchRequest())


@pytest.mark.asyncio
async def test_mixed_continuation_suggestions_and_request_validation() -> None:
    transport = transport_for({"items": [], "next": "/v1/directory/search?cursor=opaque"})
    client = DirectoryClient(transport=transport)
    page = await client.continue_search("/v1/directory/search?cursor=opaque")
    assert page.next == "/v1/directory/search?cursor=opaque"
    assert transport.requests[0].method == "GET" and not transport.requests[0].body
    for request in [
        ResourceSearchRequest(types=[]),
        ResourceSearchRequest(types=["service", "service"]),
        ResourceSearchRequest(limit=-1),
    ]:
        with pytest.raises(DirectoryError):
            await client.search(request)
    with pytest.raises(DirectoryError, match="empty"):
        await client.continue_search(" ")
    with pytest.raises(DirectoryError):
        await client.suggest(SuggestionRequest(prefix="we", limit=-1))
    assert len(transport.requests) == 1
    transport = transport_for({"items": ["Weather forecasts"]})
    names = await DirectoryClient(transport=transport).suggest(SuggestionRequest(prefix="we"))
    assert names == ["Weather forecasts"]
    assert transport.requests[0].url == "https://api.inflowpay.ai/v1/directory/suggestions"
    assert transport.requests[0].method == "POST"
    assert json.loads(transport.requests[0].body) == {"prefix": "we"}
    transport = transport_for({"items": []})
    await DirectoryClient(transport=transport).search(ResourceSearchRequest())
    assert json.loads(transport.requests[0].body) == {}


@pytest.mark.asyncio
async def test_service_suggestions_without_limit() -> None:
    transport = transport_for({"items": ["weather"]})
    assert await DirectoryClient(transport=transport).suggest_services(
        SuggestionRequest(prefix="we")
    ) == ["weather"]
    assert transport.requests[0].method == "GET"
    assert transport.requests[0].url.endswith("/v1/services/suggestions?prefix=we")


@pytest.mark.asyncio
async def test_suggestion_filters() -> None:
    transport = transport_for({"items": ["Weather"]})
    client = DirectoryClient(transport=transport)
    request = SuggestionRequest(
        prefix=" we ", limit=5, filters=ServiceFilters(keywords=["weather"])
    )
    assert await client.suggest(request) == ["Weather"]
    assert json.loads(transport.requests[0].body) == {
        "prefix": "we",
        "limit": 5,
        "filters": {"keywords": ["weather"]},
    }
    assert request.prefix == " we "
    with pytest.raises(DirectoryError, match="do not support filters"):
        await client.suggest_services(request)
    with pytest.raises(DirectoryError, match="keywords"):
        await client.suggest(SuggestionRequest(prefix="we", filters=ServiceFilters(keywords=[""])))
    assert len(transport.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"items": [" bad"]},
        {"items": ["name"] * 26},
        {"items": [False]},
        {"items": [""]},
        {"items": ["x" * 129]},
        ["name"],
    ],
)
async def test_invalid_suggestion_envelopes(body: object) -> None:
    with pytest.raises(DirectoryError):
        await DirectoryClient(transport=transport_for(body)).suggest(SuggestionRequest(prefix="x"))


@pytest.mark.asyncio
async def test_collection_and_service_aggregation_are_separate_and_bounded() -> None:
    parent = service()
    operations = parent["operations"]
    assert isinstance(operations, list)
    operations.pop()
    body = {"items": [parent], "next": "/v1/services/search?cursor=more"}
    for options in [IterationOptions(max_items=1), IterationOptions(max_pages=1)]:
        transport = transport_for(body)
        items = await DirectoryClient(transport=transport).collect_services(
            SearchRequest(), options
        )
        assert len(items) == 1 and len(transport.requests) == 1
    transport = transport_for(body)
    transport.responses.append(
        response(json.dumps({"items": [parent]}), content_type="application/json")
    )
    items = await DirectoryClient(transport=transport).collect_services(SearchRequest())
    assert len(items) == 2 and len(transport.requests) == 2


@pytest.mark.asyncio
async def test_cancellation_propagates_without_followup_requests() -> None:
    started = asyncio.Event()
    requests: list[HttpRequest] = []

    class WaitingTransport:
        async def send(self, request: HttpRequest) -> HttpResponse:
            requests.append(request)
            started.set()
            await asyncio.Future[None]()
            raise AssertionError("cancelled request resumed")

        async def aclose(self) -> None:
            pass

    client = DirectoryClient(transport=WaitingTransport())
    task = asyncio.create_task(client.search(ResourceSearchRequest()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(requests) == 1
