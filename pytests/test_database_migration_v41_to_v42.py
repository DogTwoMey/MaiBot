from sqlalchemy import create_engine
from sqlalchemy.engine import Connection
from sqlmodel import SQLModel

from src.common.database import database_model  # noqa: F401 注册当前数据库模型
from src.common.database.migrations.builtin import LatestSchemaVersionDetector
from src.common.database.migrations.models import MigrationExecutionContext
from src.common.database.migrations.schema import SQLiteSchemaInspector
from src.common.database.migrations.v36_to_v37 import create_maisaka_reply_effects_table
from src.common.database.migrations.v41_to_v42 import BEHAVIOR_TABLES, migrate_v41_to_v42


def create_historical_reply_effects(connection: Connection) -> None:
    context = MigrationExecutionContext(
        connection=connection, current_version=36, target_version=37,
        step_index=1, step_name="v36_to_v37", total_steps=1,
    )
    create_maisaka_reply_effects_table(context)
    connection.exec_driver_sql("ALTER TABLE maisaka_reply_effects ADD COLUMN request_fingerprint VARCHAR(64)")
    connection.exec_driver_sql("ALTER TABLE maisaka_reply_effects ADD COLUMN record_blob BLOB")


def test_removal_preserves_other_data_and_is_idempotent():
    with create_engine("sqlite://").begin() as connection:
        for table_name in BEHAVIOR_TABLES:
            connection.exec_driver_sql(f'CREATE TABLE "{table_name}" (id INTEGER)')
            connection.exec_driver_sql(f'INSERT INTO "{table_name}" VALUES (1)')
        for table_name in ("mai_messages", "expressions", "jargons", "high_frequency_terms"):
            connection.exec_driver_sql(f'CREATE TABLE "{table_name}" (id INTEGER)')
            connection.exec_driver_sql(f'INSERT INTO "{table_name}" VALUES (1)')
        context = MigrationExecutionContext(
            connection=connection, current_version=41, target_version=42,
            step_index=1, step_name="v41_to_v42", total_steps=1,
        )
        migrate_v41_to_v42(context)
        migrate_v41_to_v42(context)
        snapshot = SQLiteSchemaInspector().inspect(connection)
        assert not any(snapshot.has_table(name) for name in BEHAVIOR_TABLES)
        for table_name in ("mai_messages", "expressions", "jargons", "high_frequency_terms"):
            assert connection.exec_driver_sql(f'SELECT id FROM "{table_name}"').fetchall() == [(1,)]


def test_current_models_and_schema_detection_do_not_require_behavior_tables():
    with create_engine("sqlite://").begin() as connection:
        SQLModel.metadata.create_all(connection)
        create_historical_reply_effects(connection)
        snapshot = SQLiteSchemaInspector().inspect(connection)
        assert not any(snapshot.has_table(name) for name in BEHAVIOR_TABLES)
        assert LatestSchemaVersionDetector().detect_version(snapshot) == 42


def test_unversioned_v41_database_still_gets_removal_migration():
    with create_engine("sqlite://").begin() as connection:
        SQLModel.metadata.create_all(connection)
        create_historical_reply_effects(connection)
        # 结构探测必须识别旧版本，不能因提高 latest 版本号而跳过清理。
        behavior_columns = {
            "behavior_scene_clusters": "tag_distribution TEXT",
            "behavior_experience_paths": "scene_cluster_id INTEGER, action_id INTEGER, outcome_id INTEGER",
            "behavior_actions": "action_hash TEXT",
            "behavior_outcomes": "outcome_hash TEXT",
            "behavior_scene_tag_clusters": "tag_kind TEXT, tag TEXT, cluster_key TEXT",
        }
        for table_name, columns in behavior_columns.items():
            connection.exec_driver_sql(f'CREATE TABLE "{table_name}" ({columns})')
        snapshot = SQLiteSchemaInspector().inspect(connection)
        assert LatestSchemaVersionDetector().detect_version(snapshot) == 41
