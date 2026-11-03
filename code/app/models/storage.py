from pydantic import BaseModel


class UploadReportMetadata(BaseModel):
    model_uuid: str
    version: str
    pool: str
    bucket: str
    tags: str | None = None
    # ID of the unsigned original, sent with every signed copy.
    original_file_id: str
