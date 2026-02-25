from pydantic import BaseModel, Field


class ContentReviewUpdateRequest(BaseModel):
    threads_body: str = Field(min_length=1)
    threads_first_reply: str = Field(min_length=1)
    instagram_caption: str = Field(min_length=1)


class ContentReviewActionResponse(BaseModel):
    content_unit_id: str
    review_status: str
