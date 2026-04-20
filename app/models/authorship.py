from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Authorship(Base):
    __tablename__ = "authorships"

    publication_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("publications.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)

    person_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("persons.person_id", ondelete="SET NULL"),
        nullable=True,
    )
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    href: Mapped[str | None] = mapped_column(String, nullable=True)

    publication = relationship("Publication", back_populates="authorships")
    person = relationship("Person", lazy="joined")

    __table_args__ = (
        Index("ix_authorships_person_id", "person_id"),
        Index("ix_authorships_publication_id", "publication_id"),
    )
