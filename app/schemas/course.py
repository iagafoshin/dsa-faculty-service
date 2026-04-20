from pydantic import BaseModel, ConfigDict


class Course(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title: str
    url: str | None = None
    academic_year: str | None = None
    language: str | None = None
    level: str | None = None
    raw_meta: str | None = None
