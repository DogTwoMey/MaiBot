from json import dumps

from sqlalchemy import text


LEGACY_CONFIG_MIGRATION_TASK_NAME: str = "legacy_config_migration_v1"


def is_legacy_config_migration_completed() -> bool:
    """读取一次性配置迁移状态，完成后不再重复运行 legacy migration。"""

    from src.common.database.database import get_db_session

    with get_db_session() as session:
        row = session.exec(
            text(
                """
                SELECT status
                FROM one_time_maintenance_tasks
                WHERE task_name = :task_name
                """
            ),
            params={"task_name": LEGACY_CONFIG_MIGRATION_TASK_NAME},
        ).first()
    return row is not None and str(row[0] or "").strip() == "done"


def should_apply_legacy_migration(config_file_name: str) -> bool:
    """仅在一次性 legacy 配置迁移尚未完成时运行。"""

    if config_file_name != "bot_config.toml":
        return False
    return not is_legacy_config_migration_completed()


def mark_legacy_config_migration_completed(*, migrated: bool, reason: str) -> None:
    """写入 legacy 配置迁移完成状态。"""

    from src.common.database.database import get_db_session

    stats_json = dumps(
        {
            "migrated": migrated,
            "reason": reason,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    with get_db_session() as session:
        session.exec(
            text(
                """
                INSERT INTO one_time_maintenance_tasks (
                    task_name, phase, status, cursor_id, stats_json,
                    last_error, completed_at, updated_at
                )
                VALUES (
                    :task_name, 'done', 'done', 0, :stats_json,
                    NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                ON CONFLICT(task_name) DO UPDATE SET
                    phase = excluded.phase,
                    status = excluded.status,
                    cursor_id = excluded.cursor_id,
                    stats_json = excluded.stats_json,
                    last_error = NULL,
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = excluded.updated_at
                """
            ),
            params={
                "task_name": LEGACY_CONFIG_MIGRATION_TASK_NAME,
                "stats_json": stats_json,
            },
        )
