import logging
from typing import Annotated, Dict

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.core.config import settings
from app.models.requests import GenerationMetadata
from app.models.responses import (
    AIMBOMGeneratedResponse,
    SignedReportResponse,
    StatusResponse,
)
from app.services import signing
from app.services.generator import (
    AIMBOMGenerator,
    GeneratorGenerationError,
    GeneratorMissingReportError,
    GeneratorStorageError,
    get_generator,
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
    status_code=status.HTTP_200_OK,
)
def sign_report(report: Dict):
    """
    Digitally sign a report using the configured signing certificate and private key.

    This endpoint applies a cryptographic signature to the provided report,
    allowing consumers to verify its authenticity and integrity.

    **Request Body**

    `report`: A JSON report to be signed.

    **Response**

    Returns the signed report together with a confirmation message.
    """

    logger.info("Report signing requested")
    try:
        # NOTE: Maybe use asyncer to avoid blocking the event loop,
        # especially if signing is slow with loading key/certificate operations.
        signed_report = signing.sign_report(report)
        logger.info("Report signed successfully")
        return SignedReportResponse(
            detail="Report signed successfully",
            signed_report=signed_report,
        )
    except Exception as e:
        logger.error("Error signing report", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.post(
    "/generate/{model_uuid}/{model_version}",
    response_model=AIMBOMGeneratedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_aimbom(
    model_uuid: Annotated[
        str,
        Path(
            description="Unique identifier of the AI model",
            example="e6a0d3f2-085a-4a32-8844-454666b293b1",
        ),
    ],
    model_version: Annotated[
        str,
        Path(description="Version of the AI model", example="v1.0"),
    ],
    generation_metadata: GenerationMetadata,
    generator: AIMBOMGenerator = Depends(get_generator),
):
    """
    Generate an AIMBOM for a specific AI model version.

    This endpoint aggregates the provided security reports and generates
    an AI Model Bill of Materials (AIMBOM).

    **Path Parameters**

    `model_uuid`: Unique identifier of the AI model.

    `model_version`: Version of the AI model.

    **Request Body**

    `generation_metadata`: Metadata describing the reports that should be
    included in the generated AIMBOM.

    **Response**

    Returns the serial number and metadata of the generated AIMBOM.
    """

    logger.info(
        "AIMBOM generation requested for model_uuid=%s, model_version=%s",
        model_uuid,
        model_version,
    )

    try:
        aimbom = await generator.generate(
            model_uuid, model_version, generation_metadata
        )
    except GeneratorMissingReportError as e:
        logger.warning("Missing reports for model_uuid=%s: %s", model_uuid, e)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except GeneratorStorageError as e:
        logger.error("Storage error for model_uuid=%s", model_uuid, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        )
    except GeneratorGenerationError as e:
        logger.error(
            "AIMBOM generation error for model_uuid=%s", model_uuid, exc_info=True
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
        model_uuid,
        model_version,
        aimbom_uuid,
    )

    return AIMBOMGeneratedResponse(
        detail="AIMBOM generated successfully",
        aimbom_uuid=aimbom_uuid,
        model_uuid=model_uuid,
        model_version=model_version,
    )
