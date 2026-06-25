from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder

from app.config import settings
from app.db import MinioDB, MinioError, get_minio_client
from app.models.responses import ReportSavedResponse

# !This router is excluded from production and should only be used for development!
router = APIRouter(
    prefix="/dev",
    tags=["dev"],
)


@router.post(
    "/{model_uuid}/{model_version}/reports/{report_name}",
    response_model=ReportSavedResponse,
    status_code=status.HTTP_200_OK,
)
async def save_report(
    model_uuid: str,
    model_version: str,
    report_name: str,
    report: Dict,
    minio: MinioDB = Depends(get_minio_client),
):
    store_report(model_uuid, model_version, report_name, report, minio)

    return ReportSavedResponse(
        detail="Report saved successfully",
        id=report.get("serialNumber"),
        report_name=report_name,
        model_uuid=model_uuid,
        model_version=model_version,
    )


def store_report(
    model_uuid: str, model_version: str, report_name: str, report: Dict, minio: MinioDB
) -> None:
    try:
        minio.upload_json(
            bucket_name=settings.REPORTS_BUCKET,
            object_name=f"{model_uuid}/{model_version}/{report_name}.json",
            data=jsonable_encoder(report, exclude_none=True),
        )
    except MinioError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"MinIO error while saving report: {e}",
        )
