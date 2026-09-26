# Offering Discovery Protocol for Python

[![CI](https://github.com/offering-protocol/odp-python/actions/workflows/ci.yml/badge.svg)](https://github.com/offering-protocol/odp-python/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PyPI](https://img.shields.io/pypi/v/offering-protocol)](https://pypi.org/project/offering-protocol/)
[![Codecov](https://codecov.io/gh/offering-protocol/odp-python/graph/badge.svg)](https://codecov.io/gh/offering-protocol/odp-python)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

Official Python software development kit for the
[Offering Discovery Protocol](https://www.offeringprotocol.org/), the open protocol for discovering
Services and navigating their Offerings.

ODP separates two levels of discovery:

1. An Agent searches the canonical Directory for Services.
2. For a native ODP source, the Agent inspects the Service's live ODP document and navigates its Collections and
   Offerings.

The Directory does not copy every Service catalog. Catalog searches go directly to each Service.

## Installation

```sh
python -m pip install offering-protocol
```

Python 3.11 or newer is required. The distribution provides one typed package with modules for each
integration role:

| Goal | Module |
| --- | --- |
| Parse protocol models and validate normative documents | `offering_protocol.core` |
| Search the canonical production or sandbox Directory | `offering_protocol.directory` |
| Inspect Services and navigate their catalogs | `offering_protocol.agent` |
| Publish an ODP Service | `offering_protocol.service` |

## Search Services and Collections

`DirectoryClient.search()` searches indexed Services and explicitly submitted Collections.
The Directory does not crawl complete catalogs or index Offerings.

```python
import asyncio

from offering_protocol.directory import (
    CollectionResult,
    DirectoryClient,
    ResourceSearchRequest,
    ServiceResult,
    UnknownResult,
)


async def main() -> None:
    async with DirectoryClient() as directory:
        response = await directory.search(ResourceSearchRequest(query="weather forecast", limit=25))
        for item in response.items:
            if isinstance(item, ServiceResult):
                print("Service:", item.service.name, item.service.service_origin)
            elif isinstance(item, CollectionResult):
                print(
                    "Collection:",
                    item.collection.name,
                    item.collection.id,
                    item.service.service_origin,
                )
            elif isinstance(item, UnknownResult):
                print("Unsupported result type:", item.type)
        for issue in response.issues:
            print(f"Skipped result {issue.index}: {issue.message}")


asyncio.run(main())
```

`types=["service"]` or `types=["collection"]` restricts the result types. Omission selects both;
an explicit list must be nonempty and distinct. Filters apply to the owning Service's metadata.
Omit the query to browse. The default and maximum result limit are 100.

A Collection is identified by its owning `service.service_id` and case-sensitive Collection ID.
Different OpenAPI documents can share an API origin without being the same Directory Service.
When `service.source.type == "odp"`, inspect that Service's live ODP document, then call
`ServiceClient.get_collection()` for current details. OpenAPI Collections are Directory presentation
groups, not ODP operation targets. The result's `indexed_at` describes Collection freshness;
`service.indexed_at` describes parent freshness. `service.service_id` is the Directory's Service identifier. A Service result can
have optional `publisher` attribution with `publisher_id`, `name`, and `website_url`.
The website is a display link, not a discovery or execution target. Omitted or null publisher
attribution is accepted, and additional fields are preserved. A Collection's attribution is its owning `service`.

Malformed known results are omitted and reported in `issues` with their original response index.
Unknown future types retain their full JSON in `UnknownResult.raw`; do not treat them as Services
or execute their metadata. Additional fields are available through `additional`. Directory
metadata does not replace inspection of the Service's own document.

Mixed results use `DirectoryIndexedService`, separate from the native `DirectoryService` returned
by `search_services()`. Each mixed Service requires `service_id`, `service_origin`, `name`,
`indexed_at` and `source`. Imported descriptions and languages are optional; missing lists become
empty lists. Imported results do not expose native ODP operations. Native results retain ODP
validation. Unverified execution fields such as `http` and `payment_origins` are not returned.

`DirectorySource` identifies the document used for discovery:

- `type` is `"odp"`, `"openapi"`, or an unknown future string. Unknown formats remain readable
  but must not be passed to ODP operations.
- `url` is the exact document URL, including path and query. It can differ from the API origin;
  do not reconstruct it from `service_origin`.
- `x402_discovery` records supporting fixed-path x402 discovery, not proof that an endpoint
  accepts payments. Advertised protocol evidence remains in `protocols`.

The client does not fetch or execute OpenAPI documents.

Mixed search does not currently offer continuation. Missing `next` does **not** mean every match
was returned. Refine the query or filters when needed. `continue_search(next)` follows one opaque
same-origin reference if the server supplies one; the SDK does not invent continuations. Facets
count all matching targets, not just returned items: a Service and two Collections count as three.
Collection search does not require permission to display its card on the Directory landing page.

`suggest(SuggestionRequest(prefix="we", filters=ServiceFilters(keywords=["weather"])))`
sends POST `/v1/directory/suggestions`. Optional filters use the same `ServiceFilters` as search;
Collection filters apply to the owning Service. `suggest_services()` remains GET and does not
accept filters. `suggest()` matches names, descriptions and keywords, but returns
the **names of matching Services and Collections**, not the text that matched. Matching uses
substrings and whitespace-separated alternative terms despite the parameter name `prefix`.
The server deduplicates names; the default and maximum suggestion limit are 25. These strings
are candidate search queries, not resource identifiers.

See the [runnable canonical Directory example](examples/README.md#canonical-directory-discovery).

### Filter by source

```python
from offering_protocol.directory import (
    DirectoryClient,
    ResourceSearchRequest,
    ServiceFilters,
    SuggestionRequest,
)


async def discover_openapi() -> None:
    filters = ServiceFilters(sources=["openapi"])
    async with DirectoryClient() as directory:
        results = await directory.search(ResourceSearchRequest(query="weather", filters=filters))
        names = await directory.suggest(SuggestionRequest(prefix="we", filters=filters))
        print(results.items, names)
```

Omitting `sources` includes all formats. An explicit list must contain one or both distinct
`"odp"` and `"openapi"` values. Sources are alternatives, combined with other filter categories
using AND. Collections inherit their owning Service's source. Unsupported source filter values
are rejected. Native `search_services()` accepts the filter but remains ODP-only: an OpenAPI-only
filter returns no native matches.

## Search only native ODP Services

`DirectoryClient` uses the one canonical production Directory. Pass `Environment.SANDBOX` when
working against InFlow's sandbox; the endpoint itself is not configurable.

```python
import asyncio

from offering_protocol.directory import DirectoryClient, Environment, SearchRequest, ServiceFilters


async def main() -> None:
    async with DirectoryClient(Environment.PRODUCTION) as directory:
        page = await directory.search_services(
            SearchRequest(
                query="indoor plants",
                filters=ServiceFilters(keywords=["plants"]),
                limit=20,
            )
        )
        for service in page.items:
            print(service.name, service.service_origin)

        if page.next:
            next_page = await directory.continue_search_services(page.next)
            print(f"Next page contains {len(next_page.items)} Services")


asyncio.run(main())
```

Use `collect_services()` when the application wants bounded automatic pagination. It stops at the
item or response limit without fetching another response. Search responses
provide facets for enrollment protocols, keywords, operations, payment protocols, payment options,
and trust protocols. Use `suggest_services()` to discover Service-only keyword completions.

### API migration

- Mixed results use `DirectoryIndexedService` with required source metadata. Missing sources are
  reported as item issues, not assumed to be ODP. Native Service-only models are unchanged.
- Imported `description` and `language` can be `None`; check the source before ODP navigation.
- Service-only `search()` calls become `search_services()`, and `continue_search()` calls become
  `continue_search_services()`.
- Aggregating `search_services(request, options)` calls become `collect_services(request, options)`.
- `search_pages()` is removed. Applications that need individual Service-only responses can call
  `search_services()` and follow `continue_search_services()` with their own explicit limit.
- Service-only `suggest()` calls become `suggest_services()`.
- `search()`, `continue_search()`, and `suggest()` select mixed discovery.

`Agent` federated Offering discovery remains Service-only and uses `collect_services()`.

## Inspect and navigate a Service

`ServiceClient` checks the Service document before calling an operation. Calling an operation the
Service does not advertise raises `UnsupportedOperationError` before a catalog request is sent.

```python
import asyncio

from offering_protocol.agent import ServiceClient
from offering_protocol.core import OfferingSearchRequest, Representation


async def main() -> None:
    async with ServiceClient("https://demo.inflowpay.ai") as service:
        inspection = await service.inspect()
        print(inspection.document.name)
        print([operation.name.value for operation in inspection.document.operations])
        protocols = inspection.document.protocols
        print([protocol.name.value for protocol in protocols.trust] if protocols else [])

        page = await service.search_offerings(
            OfferingSearchRequest(query="plant"),
            Representation.TERSE,
        )
        for offering in page.items:
            print(offering.id, offering.name, offering.price)

        if page.items:
            details = await service.get_offering_details(page.items[0].id)
            for action in details.actions:
                print(action.id, action.rel.value, action.authentication.value)


asyncio.run(main())
```

`get_offering_details()` resolves and validates an Offering's Attribute Schema, normalizes usable
Actions, and reports non-fatal issues separately from the Offering. `resolve_action()` resolves a
specific Action's HTTP or OpenAPI target and request schema. It never calls the target, enrolls,
authenticates, or pays.

The Agent module also provides:

- Collection list, get, search, and bounded traversal operations.
- Offering list, get, search, collection listing, continuation, and bounded traversal operations.
- Effective inline and linked Filter and Sort definitions for Service and Collection scopes.
- Directory-to-Service federated Offering discovery through `Agent`.
- Conditional request and representation caching with injectable `Cache` and `Transport` protocols.

Default fallback cache lifetimes are four hours for Service documents, one hour for Collections,
five minutes for Offerings, zero for searches, one hour for Filter and Sort Definitions, and
24 hours for Attribute Schemas. Set each independently using `CacheFallbacks` (`service_document`,
`collection`, `offering`, `search`, `filters`, `sorts`, and `attribute_schema`). HTTP cache directives
take precedence. Continuations retain their originating operation's fallback; an unrecognized
continuation uses the search fallback. `ServiceClient` uses a
separate anonymous transport for linked schemas and OpenAPI documents, even when its primary
`transport` has authentication configured. An explicit `supporting_transport` override must also
send these requests anonymously; it must not share the primary transport's credentials or cookies.

### Search across Services

`Agent` composes Directory search with bounded concurrent searches of the returned Services. A
failure from one Service becomes an issue event instead of terminating results from the other
Services.

```python
from offering_protocol.agent import Agent, FederatedSearchRequest
from offering_protocol.core import OfferingSearchRequest
from offering_protocol.directory import SearchRequest


async with Agent() as agent:
    events = await agent.search_offerings_across_services(
        FederatedSearchRequest(
            services=SearchRequest(query="plant stores"),
            offerings=OfferingSearchRequest(query="rubber plant"),
            max_services=20,
            max_offerings_per_service=10,
        )
    )
    for event in events:
        if event.offering is not None:
            print(event.service.name, event.offering.name)
        else:
            print(event.service.name, event.issue)
```

### Search capabilities and Actions

Search capability resolution combines inline and linked Filter and Sort definitions into the
effective definitions available at a Service or Collection scope:

```python
capabilities = await service.get_offering_search_capabilities()
for identifier, definition in capabilities.filters.items():
    print(identifier, definition.operators)
for issue in capabilities.issues:
    print(issue.message)
```

After selecting an Offering, resolve an advertised Action by its identifier:

```python
resolved = await service.resolve_action("rubber-plant", "purchase")
if resolved.action.http is not None:
    print(resolved.action.http.url)
elif resolved.action.openapi is not None:
    print(resolved.action.openapi.url)
print(resolved.request_schema)
```

Resolution returns metadata only. The application decides whether to enroll, authenticate, pay, or
invoke the resolved target.

### Caching and HTTP transport

Clients with a supplied `transport` use separate cache partitions by default. To share cached
responses between these clients, explicitly supply the same `cache_partition` only when they use
the same authentication context. Create a new client or select a new partition when changing
credentials. SDK-owned anonymous transports can share their anonymous partition.

`MemoryCache` is the default process-local cache. Implement the `Cache` protocol when representations
must survive process restarts or share storage across workers. A custom `Transport` implements
asynchronous `send()` and `aclose()` methods. Caller-provided caches and transports remain owned by
the caller.

`HttpRequest.maximum_response_bytes` gives a custom transport the response budget. Enforce it while
reading, rather than buffering the complete response first. The built-in transport closes responses
on overflow, read failure, and cancellation. A successful response exceeding its budget raises
`TransportError` with `code="RESPONSE_LIMIT_EXCEEDED"`; `ServiceClient` preserves that code on
`AgentError`. Oversized error bodies are discarded while retaining the HTTP status and headers.

The built-in HTTP transport resolves and validates every destination before connecting, pins the
connection to a validated public address, does not inherit proxy settings from the environment, and
sends supporting-document requests without credentials. A custom transport must preserve those ODP
network and credential-isolation requirements. Local HTTP development is disabled by default; pass
`allow_local_network=True` to `ServiceClient` only for an explicit `localhost`, `127.0.0.1`, or
`[::1]` development Service.

Attribute Schema resolution accepts JSON Schema Draft 2020-12 and is limited to 256 KiB per
document, 16 documents, eight reference levels, and one MiB for the complete graph. OpenAPI
documents are limited to one MiB and 32 levels of JSON nesting. Every other ODP response is limited
to 16 levels of nesting, and the Service Document to eight. These are fixed SDK safety ceilings. Linked schema documents must
use HTTPS. Cross-document schema composition uses `$ref`; `$dynamicRef` accepts only a fragment
reference such as `#node`.

## Publish a Service

`Service` is framework-neutral. Adapt the incoming framework request to `Request`, call
`Service.handle()`, and copy the returned status, headers, and body into the framework response.

```python
from offering_protocol.core import Collection, Offering, Protocol, TrustProtocol
from offering_protocol.service import ServiceBuilder, StaticCatalog, StaticCatalogOptions

catalog = StaticCatalog(
    StaticCatalogOptions(
        collections=(Collection(id="plants", name="Plants", odp_version="1.0"),),
        offerings=(
            Offering(
                collection_ids=["plants"],
                description="A resilient indoor plant.",
                id="rubber-plant",
                name="Rubber Plant",
                odp_version="1.0",
            ),
        ),
    )
)

service = (
    ServiceBuilder(
        name="Indica Flowers",
        description="An AI-enabled store for houseplants and plant care.",
        language="en",
        endpoint_base="/odp",
    )
    .keywords(["houseplants", "indoor-plants"])
    .protocols([], [], [TrustProtocol(name=Protocol.TAP)])
    .website_url("https://example.com")
    .build(catalog)
)
```

Every Service integration must implement `list-offerings` and `get-offering`. `StaticCatalog` is the
small-Service implementation: it adds Collection operations when Collections are provided and uses
integrity-protected, stateless continuations that expire after one hour. Larger Services can
subclass the typed `Catalog` protocol over their existing indexed catalog and search infrastructure.
The protocol supplies rejecting defaults for optional operations; override an optional method and
include its matching `Operation` only when the Service implements it.

Service responses are validated against the bundled normative schemas before they are returned.
The handler enforces fixed operation paths and methods, ODP media types, request and response byte
limits, local identifiers, page limits, and protocol Problem Details.

See [examples/README.md](./examples/README.md) for a runnable Service and Agent.

## Protocol composition

ODP discovers what a Service offers and how an Agent can act on an Offering. A Service document and
its Actions can advertise enrollment, payment, and trust protocols, but ODP does not create
credentials, invoke Actions, submit payments, or implement trust protocols. Applications compose
the appropriate protocol clients around an Action resolved through ODP.

`parse_service_document` validates Service metadata against the supported ODP major version.
Compatible minor versions such as `1.7` are accepted without rewriting the received version;
SDK-generated documents use `1.0`. Agent inspection and
Directory results filter unrecognized enrollment, payment, and trust descriptors while retaining
strict validation for recognized descriptors.

Individual Offering and Collection GETs default to full representations; list and search operations
default to terse items. The Service handler writes `odp_version` on standalone resources and page
envelopes, omitting it from embedded page items without changing the Catalog's models.
A Catalog receives the requested language in `CatalogRequest.language` and
declares the language it actually returns on each resource. Static catalogs do not translate content.

Refinement parsing detects duplicate JSON values without guessing the type of a string. Comparing
decimal or date-time strings by their meaning requires the referenced Filter Definition.

## Errors and validation

Each role exposes typed errors:

- `OdpValidationError` includes deterministic schema and semantic issues.
- `DirectoryError` and `DirectoryRequestError` describe canonical Directory failures.
- `AgentError`, `ServiceRequestError`, and `UnsupportedOperationError` describe Agent-side failures.
- `ServiceError`, `CatalogError`, and `RequestError` describe Service integration failures.

Protocol models preserve additive members in `model.additional` and round-trip them through
`model.to_dict()`. Parsing remains strict for normative constraints and fields that prohibit unknown
members.

Native Service-only records retain additional metadata such as branding and MCP endpoints. Mixed
results omit unverified execution fields. Directory metadata is not authorization or authoritative
routing data. The default Agent factory uses the native record's
`service_origin` and retrieves that Service's own document before making catalog requests.

Handle the narrowest error that the application can act upon and use the role's base error for the
remaining failures:

```python
from offering_protocol.agent import AgentError, ServiceRequestError, UnsupportedOperationError

try:
    offering = await service.get_offering("rubber-plant")
except UnsupportedOperationError as error:
    print(f"Service does not advertise {error.operation.value}")
except ServiceRequestError as error:
    print(error.status, error.headers)
except AgentError as error:
    print(error)
```

## Development

Python 3.11 or newer and [uv](https://docs.astral.sh/uv/) are required.

```sh
make sync
make verify
```

Format source files with:

```sh
make format
```

The merge gate checks formatting, linting, strict type checking, 100 percent line and branch
coverage, distribution metadata, bundled runtime schemas, and installation of the built wheel into
a clean virtual environment.

Generate Agent and Service conformance reports with:

```sh
ODP_SPECS_DIR=/path/to/odp-specs make conformance
```

The language-neutral harness executes the package's public behavior and writes release evidence to
`.conformance/reports/`.

Run the Python Agent against the Node.js reference Service with:

```sh
ODP_NODE_DIR=/path/to/odp-node make interoperability
```

See [`odp-specs`](https://github.com/offering-protocol/odp-specs) for the normative draft, schemas,
examples, and test vectors.

## Security

See [SECURITY.md](./SECURITY.md) for vulnerability reporting.

## Releases

Maintainers run the `Release` workflow from `main`. It verifies the package and a clean consumer,
publishes through PyPI Trusted Publishing, attests the distributions, and creates the matching tag
and GitHub release with Agent and Service conformance reports.

## License

MIT.
