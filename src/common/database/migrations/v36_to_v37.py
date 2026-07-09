"""v36 schema 升级到 v37：补齐分叉 v36 迁移的兼容缺口。"""

from src.common.logger import get_logger

from .models import MigrationExecutionContext
from .v35_to_v36 import (
    create_mai_messages_platform_message_id_index,
    create_maisaka_monitor_events_table,
)

logger = get_logger("database_migration")


def migrate_v36_to_v37(context: MigrationExecutionContext) -> None:
    """确保已处于 v36 的数据库同时具备观察事件账本和消息平台索引。"""

    context.start_progress(
        total_tables=1,
        total_records=2,
        description="v36 -> v37 迁移进度",
        table_unit_name="表",
        record_unit_name="项",
    )

    create_maisaka_monitor_events_table(context)
    context.advance_progress(records=1, item_name="maisaka_monitor_events")
    create_mai_messages_platform_message_id_index(context)
    context.advance_progress(records=1, completed_tables=1, item_name="v36_compatibility_schema")

    logger.info("v36 -> v37 数据库迁移完成：已补齐观察事件账本与消息平台索引")
