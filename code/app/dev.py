from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder

from app.config import settings
from app.db import MinioConnectionError, MinioDB, get_minio_client
from app.models.cyclonedx import (
    AssessmentReport,
    DefenceReport,
    RiskAssessmentReport,
    SecurityReport,
)
from app.models.responses import ReportSavedResponse

# !This router is excluded from production and should only be used for development!
router = APIRouter(
    prefix="/dev",
    tags=["dev"],
)


@router.post(
    "/reports/defence",
    response_model=ReportSavedResponse,
    status_code=status.HTTP_200_OK,
)
def gather_defence_report(
    report: DefenceReport, minio: MinioDB = Depends(get_minio_client)
):
    store_report(report, minio)

    return ReportSavedResponse(
        detail="Report saved successfully",
        id=report.get_model_id(),
        model_id=report.serial_number,
    )


@router.post(
    "/reports/assessment",
    response_model=ReportSavedResponse,
    status_code=status.HTTP_200_OK,
)
def gather_assessment_report(
    report: AssessmentReport, minio: MinioDB = Depends(get_minio_client)
):
    store_report(report, minio)

    return ReportSavedResponse(
        detail="Report saved successfully",
        id=report.get_model_id(),
        model_id=report.serial_number,
    )


@router.post(
    "/reports/risk-assessment",
    response_model=ReportSavedResponse,
    status_code=status.HTTP_200_OK,
)
def gather_risk_assessment_report(
    report: RiskAssessmentReport, minio: MinioDB = Depends(get_minio_client)
):
    store_report(report, minio)

    return ReportSavedResponse(
        detail="Report saved successfully",
        id=report.get_model_id(),
        model_id=report.serial_number,
    )


def store_report(report: SecurityReport, minio: MinioDB) -> None:
    try:
        minio.upload_json(
            bucket_name=settings.REPORTS_BUCKET,
            object_name=f"{report.get_model_id()}/{report.serial_number}.json",
            data=jsonable_encoder(report, exclude_none=True),
        )
    except MinioConnectionError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"MinIO error while saving report: {e}",
        )
