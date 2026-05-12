from datetime import datetime, timezone
from typing import Type, Union

from app.models.aimbom import ReportType
from app.models.aimodel_info import AIModelInfo
from app.models.assessment_info import AssessmentInfo
from app.models.cyclonedx import CamelModel
from app.models.dataset_info import DatasetInfo
from app.models.defences_info import DefencesInfo
from app.models.euaiact_info import EUAIActInfo
from app.models.gadget_info import GadgetInfo
from app.models.risk_report_info import RiskReportInfo


def utc_now_datetime() -> datetime:
    return datetime.now(timezone.utc)
    # return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def utc_now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def uuid_from_serial_number(serial_number: str) -> str:
    if serial_number.startswith("urn:uuid:"):
        return serial_number.split("urn:uuid:")[1]
    raise ValueError(f"Invalid serial number format: {serial_number}")


REPORT_TO_COMMENT = {
    ReportType.AI_MODEL_INFO: "Model Information",
    ReportType.ASSESSMENTS: "Model Assessment Reports",
    ReportType.DATASETS: "Dataset Information",
    ReportType.DEFENCES: "Defence Report",
    ReportType.EU_AI_ACT: "Model Development Guidelines",
    ReportType.GADGETS: "Gadget List",
    ReportType.RISK_REPORT: "Risk Assessment",
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
