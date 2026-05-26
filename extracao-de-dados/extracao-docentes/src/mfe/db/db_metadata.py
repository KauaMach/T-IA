from pathlib import Path

from sqlalchemy import JSON, Float, Integer, String, Text, create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, Session, mapped_column

from src.mfe.db.base import Base


class ExtractionRecord(Base):
    __tablename__ = "extraction_records"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    pipeline: Mapped[str] = mapped_column(String, nullable=False)
    filepath: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_format: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    tokens_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text_file_s3_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    images_s3_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_started: Mapped[str | None] = mapped_column(String, nullable=True)
    extraction_finished: Mapped[str | None] = mapped_column(String, nullable=True)
    extraction_duration_in_seconds: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    class_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)


def get_session(db_path: str) -> Session:
    """Cria o engine SQLite, garante as tabelas e retorna uma Session.

    Args:
        db_path: caminho para o arquivo .db (criado automaticamente se não existir).

    Returns:
        SQLAlchemy Session pronta para uso.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}")

    Base.metadata.create_all(engine)

    return Session(engine)


def upsert_record(session: Session, record: dict, pipeline: str) -> None:
    """Insere ou atualiza um registro na tabela extraction_records.

    Args:
        session: Session retornada por get_session.
        record: dicionário com os campos do registro (sem text_content).
        pipeline: nome da pipeline que gerou o registro (ex: "docling", "deepseek").
    """
    obj = ExtractionRecord(
        id=record.get("id"),
        pipeline=pipeline,
        filepath=record.get("filepath"),
        file_format=record.get("file_format"),
        status=record.get("status"),
        tokens_count=record.get("tokens_count"),
        page_count=record.get("page_count"),
        text_file_s3_uri=record.get("text_file_s3_uri"),
        images_s3_uri=record.get("images_s3_uri"),
        extraction_started=record.get("extraction_started"),
        extraction_finished=record.get("extraction_finished"),
        extraction_duration_in_seconds=record.get("extraction_duration_in_seconds"),
        class_metadata=record.get("class_metadata"),
        error_log=record.get("error_log"),
    )

    session.merge(obj)
    session.commit()


def check_sequence_exists(session: Session) -> bool:
    """Verifica se a sequence jsonl_batch_seq existe no banco atual."""
    return session.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_sequences WHERE sequencename = 'jsonl_batch_seq')")
    ).scalar()


async def async_check_sequence_exists(session: AsyncSession) -> bool:
    """Versão assíncrona de check_sequence_exists."""
    result = await session.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_sequences WHERE sequencename = 'jsonl_batch_seq')")
    )
    return result.scalar()


def should_process_file(session: Session, record_id: str, pipeline: str) -> bool:
    """Retorna True se o arquivo deve ser processado.

    Processa se não existe no banco ou se o status é IN_PROGRESS.
    Ignora arquivos com status EXTRACTED ou FAILED.
    """
    row = session.execute(
        text(
            "SELECT status FROM extraction_records WHERE id = :id AND pipeline = :pipeline"
        ),
        {"id": record_id, "pipeline": pipeline},
    ).fetchone()
    if row is None:
        return True
    return row[0] == "IN_PROGRESS"


def get_next_batch_index(session: Session) -> int:
    """Retorna o próximo índice de batch a partir da sequence do banco."""
    return session.execute(text("SELECT nextval('jsonl_batch_seq')")).scalar()


async def async_should_process_file(
    session: AsyncSession, record_id: str, pipeline: str
) -> bool:
    """Versão assíncrona de should_process_file."""
    result = await session.execute(
        text(
            "SELECT status FROM extraction_records WHERE id = :id AND pipeline = :pipeline"
        ),
        {"id": record_id, "pipeline": pipeline},
    )
    row = result.fetchone()
    if row is None:
        return True
    return row[0] == "IN_PROGRESS"


async def async_get_next_batch_index(session: AsyncSession) -> int:
    """Versão assíncrona de get_next_batch_index."""
    result = await session.execute(text("SELECT nextval('jsonl_batch_seq')"))
    return result.scalar()


async def async_upsert_record(
    session: AsyncSession, record: dict, pipeline: str
) -> None:
    """Versão assíncrona de upsert_record para uso com AsyncSession."""
    obj = ExtractionRecord(
        id=record.get("id"),
        pipeline=pipeline,
        filepath=record.get("filepath"),
        file_format=record.get("file_format"),
        status=record.get("status"),
        tokens_count=record.get("tokens_count"),
        page_count=record.get("page_count"),
        text_file_s3_uri=record.get("text_file_s3_uri"),
        images_s3_uri=record.get("images_s3_uri"),
        extraction_started=record.get("extraction_started"),
        extraction_finished=record.get("extraction_finished"),
        extraction_duration_in_seconds=record.get("extraction_duration_in_seconds"),
        class_metadata=record.get("class_metadata"),
        error_log=record.get("error_log"),
    )

    await session.merge(obj)
    await session.commit()
