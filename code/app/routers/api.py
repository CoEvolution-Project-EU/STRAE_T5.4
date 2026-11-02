import logging
from typing import Annotated, Dict

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.core.config import settings
from app.models.requests import GenerationMetadata, SigningMetadata
from app.models.responses import (
    AIMBOMGeneratedResponse,
    SignedFile,
    SignedReportResponse,
    StatusResponse,
)
from app.services.generator import (
    AIMBOMGenerator,
    GeneratorGenerationError,
    GeneratorMissingReportError,
    GeneratorSigningError,
    GeneratorStorageError,
    get_generator,
)
from app.services.report_signer import (
    ReportSigner,
    ReportSignerInvalidFileError,
    ReportSignerMissingReportError,
    ReportSignerProcessingError,
    ReportSignerSigningError,
    ReportSignerStorageError,
    ReportSignerUploadRejectedError,
    get_signer,
)
from app.utils.utils import uuid_from_serial_number

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["api"],
)


@router.get("/status", response_model=StatusResponse, status_code=status.HTTP_200_OK)
def get_status():
    """
    Retrieve the operational status of the STR Assurance Engine API.

    This endpoint can be used for health checks, service monitoring, and
    deployment validation. A successful response indicates that the API is
    running and able to process requests.

    **Response**

    Returns the current service status and API version.
    """

    return StatusResponse(status="operational", version=settings.VERSION)


@router.post(
    "/sign",
    response_model=SignedReportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def sign_report(
    signing_metadata: SigningMetadata, signer: ReportSigner = Depends(get_signer)
):
    """
    Digitally sign reports using the configured signing certificate and private key.

    Each file is downloaded, signed and uploaded to `target_pool` /
    `target_bucket` as a signed copy of the original. Files that have already
    been signed are treated as done.

    **Request Body**

    `signing_metadata`: The files to sign and where to upload the signed
    copies, in the format of the `strae_sign_requests` Kafka event.

    **Response**

    Returns the destination and the files that were signed.
    """

    logger.info(
        "Report signing requested for model_uuid=%s, model_version=%s, files=%d",
        signing_metadata.model_uuid,
        signing_metadata.version,
        len(signing_metadata.files),
    )

    try:
        await signer.sign_and_upload(signing_metadata)
    except ReportSignerMissingReportError as e:
        logger.warning(
            "Missing report for model_uuid=%s: %s", signing_metadata.model_uuid, e
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except (ReportSignerInvalidFileError, ReportSignerUploadRejectedError) as e:
        logger.warning(
            "Invalid report for model_uuid=%s: %s", signing_metadata.model_uuid, e
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        )
    except ReportSignerStorageError as e:
        logger.error(
            "Storage error for model_uuid=%s",
            signing_metadata.model_uuid,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        )
    except ReportSignerSigningError as e:
        logger.error(
            "Signing material error for model_uuid=%s",
            signing_metadata.model_uuid,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        )
    except ReportSignerProcessingError as e:
        logger.error(
            "Report signing error for model_uuid=%s",
            signing_metadata.model_uuid,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )
    except Exception as e:
        logger.exception("Unexpected error during report signing")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )

    logger.info(
        "Reports signed: model_uuid=%s, model_version=%s, files=%d",
        signing_metadata.model_uuid,
        signing_metadata.version,
        len(signing_metadata.files),
    )

    return SignedReportResponse(
        detail="Reports signed successfully",
        model_uuid=signing_metadata.model_uuid,
        model_version=signing_metadata.version,
        target_pool=signing_metadata.target_pool,
        target_bucket=signing_metadata.target_bucket,
        files=[
            SignedFile(original_file_id=file.id, filename=file.filename)
            for file in signing_metadata.files
        ],
    )


@router.post(
    "/generate",
    response_model=AIMBOMGeneratedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_aimbom(
    generation_metadata: GenerationMetadata,
    generator: AIMBOMGenerator = Depends(get_generator),
):
    """
    Generate an AIMBOM for a specific AI model version.

    This endpoint aggregates the provided security reports and generates
    an AI Model Bill of Materials (AIMBOM).

    **Request Body**

    `generation_metadata`: Metadata describing the unique identifier and the
    version of the AI model and the reports that should be included in the generated AIMBOM.

    **Response**

    Returns the serial number and metadata of the generated AIMBOM.
    """

    logger.info(
        "AIMBOM generation requested for model_uuid=%s, model_version=%s",
        generation_metadata.model_uuid,
        generation_metadata.version,
    )

    try:
        aimbom = await generator.generate(generation_metadata)
    except GeneratorMissingReportError as e:
        logger.warning(
            "Missing reports for model_uuid=%s: %s", generation_metadata.model_uuid, e
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except GeneratorStorageError as e:
        logger.error(
            "Storage error for model_uuid=%s",
            generation_metadata.model_uuid,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        )
    except GeneratorSigningError as e:
        logger.error(
            "Signing material error for model_uuid=%s",
            generation_metadata.model_uuid,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        )
    except GeneratorGenerationError as e:
        logger.error(
            "AIMBOM generation error for model_uuid=%s",
            generation_metadata.model_uuid,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )
    except Exception as e:
        logger.exception("Unexpected error during AIMBOM generation")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )

    aimbom_uuid = uuid_from_serial_number(aimbom.serial_number)

    logger.info(
        "AIMBOM generated: model_uuid=%s, model_version=%s, serial_number=%s",
        generation_metadata.model_uuid,
        generation_metadata.version,
        aimbom_uuid,
    )

    return AIMBOMGeneratedResponse(
        detail="AIMBOM generated successfully",
        aimbom_uuid=aimbom_uuid,
        aimbom_version=aimbom.version,
        model_uuid=generation_metadata.model_uuid,
        model_version=generation_metadata.version,
    )
