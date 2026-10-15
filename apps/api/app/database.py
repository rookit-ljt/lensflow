from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine_options: dict[str, object] = {
    "pool_pre_ping": True,
    "connect_args": connect_args,
}
if settings.database_url in {"sqlite://", "sqlite:///:memory:"}:
    engine_options["poolclass"] = StaticPool

engine = create_engine(settings.database_url, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def ensure_generation_columns() -> None:
    """Add MVP generation fields to databases created before text generation existed."""
    inspector = inspect(engine)
    if "generations" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("generations")}
    columns = {
        "kind": "VARCHAR(32) NOT NULL DEFAULT 'video'",
        "model": "VARCHAR(160)",
        "node_id": "VARCHAR(36)",
        "input_text": "TEXT",
        "temperature": "FLOAT NOT NULL DEFAULT 0.7",
        "max_tokens": "INTEGER NOT NULL DEFAULT 1200",
        "parameters": "JSON NOT NULL DEFAULT '{}'",
        "output_text": "TEXT",
        "cost_credits": "INTEGER NOT NULL DEFAULT 0",
    }
    with engine.begin() as connection:
        for name, definition in columns.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE generations ADD COLUMN {name} {definition}"))


def ensure_auth_columns() -> None:
    """Keep existing databases usable when authentication and RBAC are introduced."""
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    if "users" in table_names:
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "is_admin" not in user_columns:
            bool_type = "BOOLEAN NOT NULL DEFAULT FALSE" if engine.dialect.name == "postgresql" else "INTEGER NOT NULL DEFAULT 0"
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE users ADD COLUMN is_admin {bool_type}"))

    if "projects" in table_names:
        existing = {column["name"] for column in inspector.get_columns("projects")}
        if "user_id" not in existing:
            column_type = "UUID" if engine.dialect.name == "postgresql" else "CHAR(32)"
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE projects ADD COLUMN user_id {column_type}"))
                connection.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_projects_user_id ON projects (user_id)")
                )


def ensure_workflow_columns() -> None:
    """Add revision/idempotency fields to local databases created by older builds."""
    inspector = inspect(engine)
    if "workflows" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("workflows")}
    timestamp_type = "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "TIMESTAMP"
    columns = {
        "revision": "INTEGER NOT NULL DEFAULT 0",
        "last_operation_id": "VARCHAR(120)",
        "last_operation_at": timestamp_type,
    }
    with engine.begin() as connection:
        for name, definition in columns.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE workflows ADD COLUMN {name} {definition}"))


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
