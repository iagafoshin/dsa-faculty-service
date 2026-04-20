from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PersonSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    person_id: int
    full_name: str
    avatar: str | None = None
    profile_url: str
    primary_unit: str | None = None
    campus_name: str | None = None
    publications_total: int = 0
    languages: list[str] = []


class Contacts(BaseModel):
    phones: str | None = None
    address: str | None = None
    hours: str | None = None
    timetable_url: str | None = None


class PositionUnit(BaseModel):
    name: str | None = None
    url: str | None = None


class Position(BaseModel):
    title: str | None = None
    units: list[PositionUnit] = []


class PersonRef(BaseModel):
    person_id: int | None = None
    name: str
    url: str | None = None
    role: str | None = None


class Relations(BaseModel):
    managers: list[PersonRef] = []


class Degree(BaseModel):
    year: int | None = None
    text: str


class Education(BaseModel):
    degrees: list[Degree] = []
    extra_education: list[str] = []


class Grant(BaseModel):
    title: str
    year: int | None = None
    role: str | None = None


class Person(PersonSummary):
    contacts: Contacts = Contacts()
    positions: list[Position] = []
    relations: Relations = Relations()
    education: Education = Education()
    work_experience: list[str] = []
    awards: list[str] = []
    interests: list[str] = []
    grants: list[Grant] = []
    editorial_staff: list[str] = []
    conferences: list[str] = []
    bio_notes: list[str] = []
    research_ids: dict[str, str] = {}
    parsed_at: datetime | None = None
