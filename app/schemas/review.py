from pydantic import BaseModel, Field


class ContentReviewUpdateRequest(BaseModel):
    threads_body: str = Field(min_length=1)
    threads_first_reply: str = Field(min_length=1)
    instagram_caption: str = Field(min_length=1)
    slide_script: dict | None = None
    font_style: str | None = None
    background_mode: str | None = None
    template_style: str | None = None


class ContentReviewActionResponse(BaseModel):
    content_unit_id: str
    review_status: str
