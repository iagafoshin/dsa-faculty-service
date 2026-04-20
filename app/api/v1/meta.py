from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models import Campus
from app.schemas.common import Campus as CampusSchema
from app.schemas.common import PublicationTypeMeta
from app.schemas.publication import PublicationType

router = APIRouter()


_PUB_TYPE_LABELS = {
    PublicationType.ARTICLE: "Научная статья",
    PublicationType.BOOK: "Книга",
    PublicationType.PREPRINT: "Препринт",
    PublicationType.CHAPTER: "Глава в книге",
    PublicationType.CONFERENCE: "Доклад на конференции",
    PublicationType.THESIS: "Диссертация / ВКР",
    PublicationType.OTHER: "Другое",
}


@router.get("/campuses", response_model=list[CampusSchema])
async def list_campuses(db: AsyncSession = Depends(get_db)) -> list[CampusSchema]:
    rows = (await db.execute(select(Campus).order_by(Campus.campus_name))).scalars().all()
    return [CampusSchema(campus_id=r.campus_id, campus_name=r.campus_name) for r in rows]


@router.get("/publication-types", response_model=list[PublicationTypeMeta])
async def list_publication_types() -> list[PublicationTypeMeta]:
    return [PublicationTypeMeta(code=t.value, label=_PUB_TYPE_LABELS[t]) for t in PublicationType]
