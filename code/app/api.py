import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import settings
from app.generator import (
    AIMBOMGenerator,
    GeneratorGenerationError,
    GeneratorMinioError,
    GeneratorMissingReportError,
    get_generator,
)
from app.models.responses import AIMBOMGeneratedResponse, StatusResponse

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
    "/generate/{model_id}",
    response_model=AIMBOMGeneratedResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_aimbom(model_id: str, generator: AIMBOMGenerator = Depends(get_generator)):
    """
    Generate an AIMBOM for the given model ID by aggregating reports from MinIO.

    Returns:
        AIMBOMGeneratedResponse - A response containing the details of the generated AIMBOM.
    """

    logger.info("AIMBOM generation requested for model_id=%s", model_id)

    try:
        aimbom = generator.generate(model_id)
    except GeneratorMissingReportError as e:
        logger.warning("Missing reports for model_id=%s: %s", model_id, e)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except GeneratorMinioError as e:
        logger.error("MinIO error for model_id=%s", model_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        )
    except GeneratorGenerationError as e:
        logger.error("AIMBOM generation error for model_id=%s", model_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )
    except Exception as e:
        logger.exception("Unexpected error during AIMBOM generation")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )

    logger.info(
        "AIMBOM generated: model_id=%s, serial_number=%s",
        model_id,
        aimbom.serial_number,
    )

    return AIMBOMGeneratedResponse(
        detail="AIMBOM generated successfully",
        id=aimbom.serial_number,
        model_id=model_id,
    )
