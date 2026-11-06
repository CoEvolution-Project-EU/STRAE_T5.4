from datetime import datetime, timezone
from enum import Enum
from typing import Type, Union

from app.models.aimbom import AIMBOM
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


def bom_link(serial_number: str, version: int) -> str:
    """Return the CycloneDX BOM-Link (`urn:cdx:{uuid}/{version}`) of a document.

    Args:
        serial_number: The document's serial number, `urn:uuid:{uuid}`.
        version: The document's version.

    Returns:
        The BOM-Link that an AIMBOM external reference uses to point at it.
    """

    return f"urn:cdx:{uuid_from_serial_number(serial_number)}/{version}"


class ReportType(str, Enum):
    AI_MODEL_INFO = "aimodelinfo_report"
    ASSESSMENTS = "assessment_report"
    DATASETS = "datasets_report"
    DEFENCES = "defence_report"
    EU_AI_ACT = "euaiact_report"
    GADGETS = "gadgets_report"
    RISK_REPORT = "risk_report"


class BOMType(str, Enum):
    """Documents that are validated like reports but are not reports."""

    AIMBOM = "aimbom"


# A report type, or `BOMType.AIMBOM`.
DocumentType = Union[ReportType, BOMType]


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


# Report types that must be present when updating (deprecating) an existing AIMBOM.
REQUIRED_UPDATABLE_REPORT_TYPES = (ReportType.ASSESSMENTS, ReportType.RISK_REPORT)

# Report types that may be present when updating (deprecating) an existing AIMBOM.
OPTIONAL_UPDATABLE_REPORT_TYPES = (ReportType.GADGETS,)


REPORT_TO_COMMENT = {
    ReportType.AI_MODEL_INFO: ReportComment.AI_MODEL_INFO,
    ReportType.ASSESSMENTS: ReportComment.ASSESSMENTS,
    ReportType.DATASETS: ReportComment.DATASETS,
    ReportType.DEFENCES: ReportComment.DEFENCES,
    ReportType.EU_AI_ACT: ReportComment.EU_AI_ACT,
    ReportType.GADGETS: ReportComment.GADGETS,
    ReportType.RISK_REPORT: ReportComment.RISK_REPORT,
}

# The reverse of `REPORT_TO_COMMENT`, to find the report type of an AIMBOM
# external reference from its comment.
COMMENT_TO_REPORT = {
    comment: report_type for report_type, comment in REPORT_TO_COMMENT.items()
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

# The model of each document type: the report models, plus the AIMBOM.
DOCUMENT_MODELS: dict[DocumentType, Type[CamelModel]] = {
    **REPORT_MODELS,
    BOMType.AIMBOM: AIMBOM,
}
