from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Campus(Base):
    __tablename__ = "campuses"

    campus_id: Mapped[str] = mapped_column(primary_key=True)
    campus_name: Mapped[str] = mapped_column(nullable=False)
