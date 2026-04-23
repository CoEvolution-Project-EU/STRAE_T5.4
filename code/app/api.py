import logging
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, status

from app import signing
from app.config import settings
from app.generator import (
    AIMBOMGenerator,
    GeneratorGenerationError,
    GeneratorMinioError,
    GeneratorMissingReportError,
    get_generator,
)
from app.models.responses import (
    AIMBOMGeneratedResponse,
    SignedReportResponse,
    StatusResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["api"],
)


@router.get("/status", response_model=StatusResponse, status_code=status.HTTP_200_OK)
def get_status():
    """
    Health check endpoint for the STRAE API.

    Returns:
        StatusResponse - A response indicating the operational status and version information.
    """

    return StatusResponse(status="operational", version=settings.VERSION)


@router.post(
    "/sign",
    response_model=SignedReportResponse,
    status_code=status.HTTP_200_OK,
)
def sign_report(report: Dict):
    """
    Sign the given report using the configured signing key.

    Args:
        report (Dict) - The report to be signed.

    Returns:
        SignedReportResponse - The signed report payload wrapped in a response model.
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
def generate_aimbom(
    model_uuid: str,
    model_version: str,
    generator: AIMBOMGenerator = Depends(get_generator),
):
    """
    Generate an AIMBOM for the given model ID by aggregating reports from MinIO.

    Args:
        model_uuid (str) - The ID of the model for which to generate the AIMBOM.
        model_version (str) - The version of the model for which to generate the AIMBOM.

    Returns:
        AIMBOMGeneratedResponse - A response containing the details of the generated AIMBOM.
    """

    logger.info(
        "AIMBOM generation requested for model_uuid=%s, model_version=%s",
        model_uuid,
        model_version,
    )

    try:
        # TODO: Use asyncer to run the generation to avoid blocking the event loop,
        # especially if MinIO operations are slow.
        # TODO: Maybe implement caching of generated AIMBOMs to avoid regenerating
        # for the same model_uuid & model_version if reports haven't changed.
        aimbom = generator.generate(model_uuid, model_version)
    except GeneratorMissingReportError as e:
        logger.warning("Missing reports for model_uuid=%s: %s", model_uuid, e)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except GeneratorMinioError as e:
        logger.error("MinIO error for model_uuid=%s", model_uuid, exc_info=True)
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

    logger.info(
        "AIMBOM generated: model_uuid=%s, model_version=%s, serial_number=%s",
        model_uuid,
        model_version,
        aimbom.serial_number,
    )

    return AIMBOMGeneratedResponse(
        detail="AIMBOM generated successfully",
        id=aimbom.serial_number,
        model_uuid=model_uuid,
        model_version=model_version,
    )
