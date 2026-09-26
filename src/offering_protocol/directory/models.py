"""Canonical Directory request and response models."""

from __future__ import annotations

from enum import StrEnum
from typing import Generic, Literal, TypeAlias, TypeVar

from pydantic import Field, JsonValue

from offering_protocol.core.models import (
    AuthenticationRequirement,
    EnrollmentProtocol,
    OdpModel,
    Operation,
    OperationDescriptor,
    PaymentOption,
    PaymentProtocol,
    Protocol,
    ServiceProtocols,
    TrustProtocol,
)

FacetValue = TypeVar("FacetValue")


class Environment(StrEnum):
    PRODUCTION = "production"
    SANDBOX = "sandbox"

    @property
    def origin(self) -> str:
        if self is Environment.PRODUCTION:
            return "https://api.inflowpay.ai"
        return "https://sandbox.inflowpay.ai"


class OperationFilter(OdpModel):
    authentication: AuthenticationRequirement | None = None
    name: Operation


class PaymentFilter(OdpModel):
    authentication: AuthenticationRequirement | None = None
    name: Protocol
    options: list[PaymentOption] = Field(default_factory=list)


class ServiceFilters(OdpModel):
    enrollment: list[EnrollmentProtocol] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    operations: list[OperationFilter] = Field(default_factory=list)
    payments: list[PaymentFilter] = Field(default_factory=list)
    sources: list[Literal["odp", "openapi"]] | None = None
    trust: list[TrustProtocol] = Field(default_factory=list)


class SearchRequest(OdpModel):
    filters: ServiceFilters | None = None
    limit: int = 0
    query: str = ""


class ResourceSearchRequest(SearchRequest):
    types: list[Literal["service", "collection"]] | None = None


class DirectoryService(OdpModel):
    description: str
    documentation_url: str = ""
    indexed_at: str
    keywords: list[str] = Field(default_factory=list)
    language: str
    localizations: list[str]
    name: str
    operations: list[OperationDescriptor]
    protocols: ServiceProtocols | None = None
    service_origin: str
    status_url: str = ""
    support_url: str = ""
    website_url: str = ""

    @property
    def service_id(self) -> str | None:
        value = self.additional.get("service_id")
        return value if isinstance(value, str) else None


class DirectorySource(OdpModel):
    type: str
    url: str
    x402_discovery: bool


class DirectoryIndexedService(OdpModel):
    description: str | None = None
    documentation_url: str | None = None
    indexed_at: str
    keywords: list[str] = Field(default_factory=list)
    language: str | None = None
    localizations: list[str] = Field(default_factory=list)
    name: str
    operations: list[OperationDescriptor] = Field(default_factory=list)
    protocols: ServiceProtocols | None = None
    service_id: str
    service_origin: str
    source: DirectorySource
    status_url: str | None = None
    support_url: str | None = None
    website_url: str | None = None


class Publisher(OdpModel):
    publisher_id: str
    name: str
    website_url: str


class CollectionSummary(OdpModel):
    id: str
    name: str
    description: str | None = None


class ServiceResult(OdpModel):
    type: Literal["service"]
    service: DirectoryIndexedService
    indexed_at: str
    publisher: Publisher | None = None


class CollectionResult(OdpModel):
    type: Literal["collection"]
    service: DirectoryIndexedService
    indexed_at: str
    collection: CollectionSummary


class UnknownResult(OdpModel):
    type: str
    raw: dict[str, JsonValue]


DirectoryResult: TypeAlias = ServiceResult | CollectionResult | UnknownResult


class DirectoryIssue(OdpModel):
    index: int
    message: str


class PaymentOptionFacetValue(OdpModel):
    name: Protocol
    option: PaymentOption


class Facet(OdpModel, Generic[FacetValue]):
    count: int
    value: FacetValue


class Facets(OdpModel):
    enrollment: list[Facet[EnrollmentProtocol]] = Field(default_factory=list)
    keywords: list[Facet[str]] = Field(default_factory=list)
    operations: list[Facet[OperationDescriptor]] = Field(default_factory=list)
    payment_options: list[Facet[PaymentOptionFacetValue]] = Field(default_factory=list)
    payments: list[Facet[PaymentProtocol]] = Field(default_factory=list)
    trust: list[Facet[TrustProtocol]] = Field(default_factory=list)


class ServiceIssue(OdpModel):
    """A record the Directory published that this client would not hand back.

    ROLE-03: a Directory result is discovery metadata rather than authoritative Service data, so
    one unusable record is a note about that record, not a reason to withhold every other Service
    on the page.
    """

    index: int
    message: str


class SearchPage(OdpModel):
    facets: Facets | None = None
    #: The records this client was able to read. Withheld records appear in `issues`.
    items: list[DirectoryService]
    issues: list[ServiceIssue] = Field(default_factory=list)
    next: str = ""


class SearchResponse(OdpModel):
    facets: Facets | None = None
    items: list[DirectoryResult]
    next: str | None = None
    issues: list[DirectoryIssue] = Field(default_factory=list)


class SuggestionRequest(OdpModel):
    filters: ServiceFilters | None = None
    limit: int = 0
    prefix: str


class IterationOptions(OdpModel):
    max_items: int = 0
    max_pages: int = 0
