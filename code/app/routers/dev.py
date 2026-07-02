from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder

from app.clients.base import StorageError
from app.clients.minio_client import MinioClient, get_minio_client
from app.core.config import settings
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
    minio: MinioClient = Depends(get_minio_client),
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
    model_uuid: str,
    model_version: str,
    report_name: str,
    report: Dict,
    minio: MinioClient,
) -> None:
    """Persist a report to MinIO used by the development API.

    Args:
        model_uuid: Model UUID to use as object prefix.
        model_version: Model version to use as object prefix.
        report_name: The name of the report file (without extension).
        report: The JSON-compatible report payload.
        minio: The `MinioClient` client to use for uploading.
    """

    try:
        minio.upload_json(
            bucket_name=settings.REPORTS_BUCKET,
            object_name=f"{model_uuid}/{model_version}/{report_name}.json",
            data=jsonable_encoder(report, exclude_none=True),
        )
    except StorageError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"MinIO error while saving report: {e}",
        )
