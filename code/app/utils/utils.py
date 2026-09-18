from datetime import datetime, timezone
from enum import Enum
from typing import Type, Union

from app.models.aimodel_info import AIModelInfo
from app.models.assessment_info import AssessmentInfo
from app.models.cyclonedx import CamelModel
from app.models.dataset_info import DatasetInfo
from app.models.defences_info import DefencesInfo
from app.models.euaiact_info import EUAIActInfo
from app.models.gadget_info import GadgetInfo
from app.models.risk_report_info import RiskReportInfo


def utc_now_datetime() -> datetime:
    """Return the current UTC datetime with tzinfo set to UTC.

    Returns:
        A `datetime` instance set to UTC.
    """

    return datetime.now(timezone.utc)
    # return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def utc_now_str() -> str:
    """Return the current UTC time as an ISO 8601 formatted string.

    Returns:
        An ISO 8601 formatted UTC timestamp string.
    """

    return datetime.now(timezone.utc).isoformat()


def uuid_from_serial_number(serial_number: str) -> str:
    """Extract the UUID portion from a CycloneDX serial number string.

    Args:
        serial_number: A serial number prefixed with `urn:uuid:`.

    Returns:
        The UUID string without the `urn:uuid:` prefix.

    Raises:
        ValueError: If the serial number is not in the expected format.
    """

    if serial_number.startswith("urn:uuid:"):
        return serial_number.split("urn:uuid:")[1]
    raise ValueError(f"Invalid serial number format: {serial_number}")


class AIMBOMTier(str, Enum):
    TIER_1 = "tier-1"
    TIER_2 = "tier-2"
    TIER_3 = "tier-3"


class ReportType(str, Enum):
    AI_MODEL_INFO = "aimodelinfo_report"
    ASSESSMENTS = "assessment_report"
    DATASETS = "datasets_report"
    DEFENCES = "defence_report"
    EU_AI_ACT = "euaiact_report"
    GADGETS = "gadgets_report"
    RISK_REPORT = "risk_report"


class ReportComment(str, Enum):
    AI_MODEL_INFO = "Model Information"
    ASSESSMENTS = "Model Assessment Reports"
    DATASETS = "Dataset Information"
    DEFENCES = "Defence Report"
    EU_AI_ACT = "Model Development Guidelines"
    GADGETS = "Gadget List"
    RISK_REPORT = "Risk Assessment"


REPORT_TYPES = (
    ReportType.AI_MODEL_INFO,
    ReportType.ASSESSMENTS,
    ReportType.DATASETS,
    ReportType.DEFENCES,
    ReportType.EU_AI_ACT,
    ReportType.GADGETS,
    ReportType.RISK_REPORT,
)


# Report types expected to change when updating an existing AIMBOM.
# TODO: Check whether the defence or any other report should also be updatable.
UPDATABLE_REPORT_TYPES = (ReportType.ASSESSMENTS, ReportType.RISK_REPORT)

# Which report comments' external references are kept in each AIMBOM tier.
# TIER_3 (the full AIMBOM) isn't listed here since it keeps every reference.
TIER_REPORT_COMMENTS: dict[AIMBOMTier, set[ReportComment]] = {
    AIMBOMTier.TIER_1: {ReportComment.EU_AI_ACT},
    AIMBOMTier.TIER_2: {
        ReportComment.EU_AI_ACT,
        ReportComment.RISK_REPORT,
        ReportComment.ASSESSMENTS,
        ReportComment.DEFENCES,
        ReportComment.GADGETS,
    },
}

REPORT_TO_COMMENT = {
    ReportType.AI_MODEL_INFO: ReportComment.AI_MODEL_INFO,
    ReportType.ASSESSMENTS: ReportComment.ASSESSMENTS,
    ReportType.DATASETS: ReportComment.DATASETS,
    ReportType.DEFENCES: ReportComment.DEFENCES,
    ReportType.EU_AI_ACT: ReportComment.EU_AI_ACT,
    ReportType.GADGETS: ReportComment.GADGETS,
    ReportType.RISK_REPORT: ReportComment.RISK_REPORT,
}

REPORT_MODELS: dict[ReportType, Type[CamelModel]] = {
    ReportType.AI_MODEL_INFO: AIModelInfo,
    ReportType.ASSESSMENTS: AssessmentInfo,
    ReportType.DATASETS: DatasetInfo,
    ReportType.DEFENCES: DefencesInfo,
    ReportType.EU_AI_ACT: EUAIActInfo,
    ReportType.GADGETS: GadgetInfo,
    ReportType.RISK_REPORT: RiskReportInfo,
}

ReportModel = Union[
    AIModelInfo,
    AssessmentInfo,
    DatasetInfo,
    DefencesInfo,
    EUAIActInfo,
    GadgetInfo,
    RiskReportInfo,
]
