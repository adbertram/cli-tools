"""Scrunch CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.
"""
from .base import CLIModel
from .brand import Brand, CreateBrand, UpdateBrand, create_brand
from .competitor import Competitor, CreateCompetitor, UpdateCompetitor, create_competitor
from .persona import Persona, CreatePersona, UpdatePersona, create_persona
from .prompt import Prompt, CreatePrompt, PromptStage, AIPlatform, create_prompt
from .query import QueryResult, QueryResponse, create_query_result
from .response import ResponseListing, create_response_listing
from .page_audit import PageAuditRecord, CreatePageAudit, PageTestListing, PageTestResponse, create_page_audit
from .agent_traffic import AgentTrafficRow, AgentTrafficResponse, create_agent_traffic_row

__all__ = [
    # Base
    "CLIModel",
    # Brand
    "Brand",
    "CreateBrand",
    "UpdateBrand",
    "create_brand",
    # Competitor
    "Competitor",
    "CreateCompetitor",
    "UpdateCompetitor",
    "create_competitor",
    # Persona
    "Persona",
    "CreatePersona",
    "UpdatePersona",
    "create_persona",
    # Prompt
    "Prompt",
    "CreatePrompt",
    "PromptStage",
    "AIPlatform",
    "create_prompt",
    # Query
    "QueryResult",
    "QueryResponse",
    "create_query_result",
    # Response
    "ResponseListing",
    "create_response_listing",
    # Page Audit
    "PageAuditRecord",
    "CreatePageAudit",
    "PageTestListing",
    "PageTestResponse",
    "create_page_audit",
    # Agent Traffic
    "AgentTrafficRow",
    "AgentTrafficResponse",
    "create_agent_traffic_row",
]
