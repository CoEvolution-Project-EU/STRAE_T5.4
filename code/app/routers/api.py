import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.core.config import settings
from app.models.requests import GenerationMetadata, SigningMetadata
from app.models.responses import (
    AIMBOMGeneratedResponse,
    AIMBOMValidationResponse,
    SignedFile,
    SignedReportResponse,
    StatusResponse,
)
from app.services.generator import (
    AIMBOMGenerator,
    GeneratorGenerationError,
    GeneratorInvalidReportError,
    GeneratorMissingReportError,
    GeneratorSigningError,
    GeneratorStorageError,
    GeneratorUploadRejectedError,
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
from app.services.validator import (
    AIMBOMValidator,
    ValidatorInvalidAIMBOMError,
    ValidatorNotFoundError,
    ValidatorReadError,
    ValidatorStorageError,
    get_validator,
)
from app.utils.utils import uuid_from_serial_number

logger = logging.getLogger(__name__)

# Response detail for unexpected errors.
INTERNAL_ERROR_DETAIL = "Internal server error"

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

    Returns the destination, the files of the request, and how many of them
    were signed by this request (`signed`) or had already been signed
    (`already_signed`).
    """

    logger.info(
        "Report signing requested for model_uuid=%s, model_version=%s, files=%d",
        signing_metadata.model_uuid,
        signing_metadata.version,
        len(signing_metadata.files),
    )

    try:
        result = await signer.sign_and_upload(signing_metadata)
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
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
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
    except Exception:
        logger.exception("Unexpected error during report signing")
        # The exception's own text is only logged: it means nothing to the
        # caller and may expose internals.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=INTERNAL_ERROR_DETAIL,
        )

    logger.info(
        "Signing request completed: model_uuid=%s, model_version=%s, "
        "signed=%d, already_signed=%d",
        signing_metadata.model_uuid,
        signing_metadata.version,
        result.signed,
        result.already_signed,
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
        signed=result.signed,
        already_signed=result.already_signed,
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
    except GeneratorInvalidReportError as e:
        logger.warning(
            "Invalid report for model_uuid=%s: %s", generation_metadata.model_uuid, e
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        )
    except GeneratorUploadRejectedError as e:
        logger.warning(
            "AIMBOM rejected by storage for model_uuid=%s: %s",
            generation_metadata.model_uuid,
            e,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        )
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
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
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
    except Exception:
        logger.exception("Unexpected error during AIMBOM generation")
        # The exception's own text is only logged: it means nothing to the
        # caller and may expose internals.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=INTERNAL_ERROR_DETAIL,
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


@router.get(
    "/validation/{uuid}/{version}",
    response_model=AIMBOMValidationResponse,
    status_code=status.HTTP_200_OK,
)
async def validate_aimbom(
    uuid: Annotated[
        str,
        Path(
            description="Unique identifier of the AI model",
            example="163723c9-173b-4ce2-abc1-4de2b25a7012",
        ),
    ],
    version: Annotated[
        str,
        Path(description="Version of the AI model", example="v1.0"),
    ],
    validator: AIMBOMValidator = Depends(get_validator),
):
    """
    Validate the AIMBOM of a specific AI model version and its reports.

    The AIMBOM and its reports are fetched from storage, validated against
    the CycloneDX schema and their models, and the AIMBOM's references are
    checked against the reports. Validation stops at the first problem.

    **Response**

    `status` is `VALID` if every check passed. If not, `status` is `INVALID`
    and `detail` describes the first problem found. Returns 404 if the model
    version has no AIMBOM and 503 if storage is unavailable.
    """

    logger.info(
        "AIMBOM validation requested for model_uuid=%s, model_version=%s",
        uuid,
        version,
    )

    try:
        await validator.validate_aimbom(uuid, version)
    except ValidatorInvalidAIMBOMError as e:
        logger.warning("Invalid AIMBOM for model_uuid=%s: %s", uuid, e)
        return AIMBOMValidationResponse(
            detail=str(e), model_uuid=uuid, model_version=version, status="INVALID"
        )
    except ValidatorNotFoundError as e:
        logger.warning("AIMBOM not found for model_uuid=%s: %s", uuid, e)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValidatorStorageError as e:
        logger.error("Storage error for model_uuid=%s", uuid, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        )
    except ValidatorReadError as e:
        logger.error("Storage read error for model_uuid=%s", uuid, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )
    except Exception:
        logger.exception("Unexpected error during AIMBOM validation")
        # The exception's own text is only logged: it means nothing to the
        # caller and may expose internals.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=INTERNAL_ERROR_DETAIL,
        )

    return AIMBOMValidationResponse(
        detail="AIMBOM validation completed",
        model_uuid=uuid,
        model_version=version,
        status="VALID",
    )
