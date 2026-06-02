"""Globiflow CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.

Model Hierarchy:
- Step (base)
  - FilterStep: FieldChangedFilter, FieldValueMatchFilter, CreatorEditorFilter, etc.
  - CollectorStep: GetReferencedItemsCollector, SearchForItemsCollector, etc.
  - LogicStep: VariableCalcStep, IfSanityCheckStep, SortCollectedStep, etc.
  - ActionStep: HttpCallStep, SendEmailStep, UpdateItemStep, etc.
"""
from .base import CLIModel
from .flow import Flow, FlowDetail, FlowLog, Trigger, TriggerType
from .step import (
    # Base models
    Step,
    AnyStep,
    create_step,

    # Category base models
    FilterStep,
    CollectorStep,
    LogicStep,
    ActionStep,

    # Filter step types
    FieldChangedFilter,
    FieldValueMatchFilter,
    CreatorEditorFilter,
    CustomCalcFilter,
    DateMatchFilter,
    CommentMatchFilter,

    # Collector step types
    GetReferencedItemsCollector,
    SearchForItemsCollector,
    GetPodioViewCollector,

    # Logic step types
    VariableCalcStep,
    IfSanityCheckStep,
    SortCollectedStep,
    ForEachStep,
    DetailTableStep,

    # Action step types
    HttpCallStep,
    SendEmailStep,
    SendSmsStep,
    SendMessageStep,
    AddCommentStep,
    AssignTaskStep,
    UpdateItemStep,
    CreateItemStep,
    MakePdfStep,
    BuildExcelStep,
    TriggerFlowStep,
    TriggerFlowOnRelatedStep,
    UpdateWidgetStep,
    DisplayPageStep,

    # Enums
    StepCategory,
    HttpMethod,
    ComparisonOperator,
    RelationshipDirection,
    SortDirection,
    AttachmentOption,
    ReplyHandling,
    AuthenticationMode,
    IterateOver,
    PageSize,
    PageOrientation,
    DateMatchType,
    CreatorEditorCheckType,
    FileSelection,
    TaskSelection,
)

__all__ = [
    # Base
    "CLIModel",

    # Flow Models
    "Flow",
    "FlowDetail",
    "FlowLog",
    "Trigger",
    "TriggerType",

    # Step Base Models
    "Step",
    "AnyStep",
    "create_step",

    # Category Base Models
    "FilterStep",
    "CollectorStep",
    "LogicStep",
    "ActionStep",

    # Filter Step Types
    "FieldChangedFilter",
    "FieldValueMatchFilter",
    "CreatorEditorFilter",
    "CustomCalcFilter",
    "DateMatchFilter",
    "CommentMatchFilter",

    # Collector Step Types
    "GetReferencedItemsCollector",
    "SearchForItemsCollector",
    "GetPodioViewCollector",

    # Logic Step Types
    "VariableCalcStep",
    "IfSanityCheckStep",
    "SortCollectedStep",
    "ForEachStep",
    "DetailTableStep",

    # Action Step Types
    "HttpCallStep",
    "SendEmailStep",
    "SendSmsStep",
    "SendMessageStep",
    "AddCommentStep",
    "AssignTaskStep",
    "UpdateItemStep",
    "CreateItemStep",
    "MakePdfStep",
    "BuildExcelStep",
    "TriggerFlowStep",
    "TriggerFlowOnRelatedStep",
    "UpdateWidgetStep",
    "DisplayPageStep",

    # Enums
    "StepCategory",
    "HttpMethod",
    "ComparisonOperator",
    "RelationshipDirection",
    "SortDirection",
    "AttachmentOption",
    "ReplyHandling",
    "AuthenticationMode",
    "IterateOver",
    "PageSize",
    "PageOrientation",
    "DateMatchType",
    "CreatorEditorCheckType",
    "FileSelection",
    "TaskSelection",
]
