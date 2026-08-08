"""v35 schema 升级到 v36：新增麦麦观察事件账本和消息索引。"""

from src.common.logger import get_logger

from .models import MigrationExecutionContext

logger = get_logger("database_migration")

MAI_MESSAGES_PLATFORM_MESSAGE_ID_INDEX = "ix_mai_messages_platform_message_id"


def migrate_v35_to_v36(context: MigrationExecutionContext) -> None:
    """创建观察事件账本，并为 ``mai_messages`` 创建 ``platform + message_id`` 查询索引。"""

    context.start_progress(
        total_tables=1,
        total_records=2,
        description="v35 -> v36 迁移进度",
        table_unit_name="表",
        record_unit_name="项",
    )

    create_maisaka_monitor_events_table(context)
    context.advance_progress(records=1, item_name="maisaka_monitor_events")
    create_mai_messages_platform_message_id_index(context)
    context.advance_progress(records=1, completed_tables=1, item_name=MAI_MESSAGES_PLATFORM_MESSAGE_ID_INDEX)

    logger.info("v35 -> v36 数据库迁移完成：麦麦观察事件账本与消息平台索引已就绪")


def create_maisaka_monitor_events_table(context: MigrationExecutionContext) -> None:
    """创建麦麦观察事件账本表及查询索引。"""

    connection = context.connection
    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS maisaka_monitor_events (
            event_id INTEGER NOT NULL,
            event_type VARCHAR(100) NOT NULL,
            session_id VARCHAR(255) NOT NULL,
            timestamp FLOAT NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1,
            payload_json TEXT NOT NULL,
            created_at DATETIME,
            PRIMARY KEY (event_id)
        )
        """
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_maisaka_monitor_events_event_type "
        "ON maisaka_monitor_events (event_type)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_maisaka_monitor_events_session_id "
        "ON maisaka_monitor_events (session_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_maisaka_monitor_events_session_event "
        "ON maisaka_monitor_events (session_id, event_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_maisaka_monitor_events_type_event "
        "ON maisaka_monitor_events (event_type, event_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_maisaka_monitor_events_timestamp "
        "ON maisaka_monitor_events (timestamp)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_maisaka_monitor_events_created_at "
        "ON maisaka_monitor_events (created_at)"
    )


def create_mai_messages_platform_message_id_index(context: MigrationExecutionContext) -> None:
    """创建消息平台与消息 ID 复合索引，避免按平台索引回表扫描大量消息。"""

    context.connection.exec_driver_sql(
        f"CREATE INDEX IF NOT EXISTS {MAI_MESSAGES_PLATFORM_MESSAGE_ID_INDEX} "
        "ON mai_messages (platform, message_id)"
    )
