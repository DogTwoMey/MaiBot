"""v34 schema 升级到 v35：清理食物化人设锚点学习污染。"""

from typing import Any, Sequence

from sqlalchemy.engine import Connection

from src.common.logger import get_logger

from .models import MigrationExecutionContext
from .schema import SQLiteSchemaInspector

logger = get_logger("database_migration")

_FOOD_ANCHOR_JARGON_CONTENTS = (
    "美食大军",
    "小饼干",
    "挠挠增甜法",
    "蜂蜜小熊饼干",
    "抓到一只偷饼干的小猫咪",
    "双倍跳跳糖",
)
_SANITIZED_JARGON_MEANINGS = {
    "痒痒": "在当前聊天语境中指轻挠带来的发笑和亲密互动。仅用于理解挠痒相关话题，不包含奖励或诱导含义。",
    "利息": "在当前聊天语境中指玩笑式追加的小互动或回应要求，用来轻松表示稍后补偿或兑现，不包含物质奖励含义。",
    "账上": "在当前聊天语境中指把约定或玩笑记录下来以后再提，不包含物质奖励含义。",
}
_FOOD_ANCHOR_TERMS = (
    "小熊饼干",
    "饼干",
    "厨娘",
    "厨房",
    "做饭",
    "烹饪",
    "食堂",
    "美食",
    "料理",
    "冰淇淋",
    "甜品",
    "小摊",
    "夜宵",
    "便当",
    "炖肉",
    "松饼",
)
_FOOD_ANCHOR_BEHAVIOR_TAGS = ("美食承诺", "做饼干", "烹饪约定")


def migrate_v34_to_v35(context: MigrationExecutionContext) -> None:
    """清理由历史聊天学出的食物化黑话与行为标签。"""

    context.start_progress(
        total_tables=3,
        total_records=_count_food_anchor_pollution(context.connection),
        description="v34 -> v35 迁移进度",
        table_unit_name="类数据",
        record_unit_name="条",
    )

    cleanup_stats = cleanup_food_anchor_learning_pollution(context.connection)
    changed_records = sum(cleanup_stats.values())
    context.advance_progress(records=changed_records, completed_tables=3, item_name="learning_pollution")

    logger.info(
        "v34 -> v35 数据库迁移完成：禁用黑话=%s, 改写黑话=%s, 删除行为路径=%s, "
        "删除行为动作=%s, 删除行为结果=%s, 删除行为标签=%s",
        cleanup_stats["disabled_jargons"],
        cleanup_stats["sanitized_jargons"],
        cleanup_stats["deleted_behavior_paths"],
        cleanup_stats["deleted_behavior_actions"],
        cleanup_stats["deleted_behavior_outcomes"],
        cleanup_stats["deleted_behavior_tags"],
    )


def cleanup_food_anchor_learning_pollution(connection: Connection) -> dict[str, int]:
    """清理历史学习中会把回复拉回厨房/饼干/美食话题的污染数据。"""

    return {
        **_cleanup_jargon_food_anchor_pollution(connection),
        **_cleanup_behavior_food_anchor_pollution(connection),
    }


def _count_food_anchor_pollution(connection: Connection) -> int:
    stats = cleanup_food_anchor_learning_pollution_dry_run(connection)
    return sum(stats.values())


def cleanup_food_anchor_learning_pollution_dry_run(connection: Connection) -> dict[str, int]:
    """只统计将被清理的数据量，不写入数据库。"""

    return {
        **_count_jargon_food_anchor_pollution(connection),
        **_count_behavior_food_anchor_pollution(connection),
    }


def _cleanup_jargon_food_anchor_pollution(connection: Connection) -> dict[str, int]:
    if not _has_table(connection, "jargons"):
        return {"disabled_jargons": 0, "sanitized_jargons": 0}

    disabled_jargons = _disable_ai_jargons_by_content(connection, _FOOD_ANCHOR_JARGON_CONTENTS)
    sanitized_jargons = 0
    for content, sanitized_meaning in _SANITIZED_JARGON_MEANINGS.items():
        cursor = connection.exec_driver_sql(
            """
            UPDATE jargons
            SET meaning = ?,
                updated_timestamp = CURRENT_TIMESTAMP
            WHERE content = ?
              AND COALESCE(created_by, 'AI') <> 'USER'
              AND COALESCE(is_jargon, 0) = 1
              AND (
                  meaning LIKE '%饼干%'
                  OR meaning LIKE '%美食%'
                  OR meaning LIKE '%甜品%'
                  OR meaning LIKE '%冰淇淋%'
                  OR meaning LIKE '%食物%'
              )
            """,
            (sanitized_meaning, content),
        )
        sanitized_jargons += int(cursor.rowcount or 0)

    return {"disabled_jargons": disabled_jargons, "sanitized_jargons": sanitized_jargons}


def _count_jargon_food_anchor_pollution(connection: Connection) -> dict[str, int]:
    if not _has_table(connection, "jargons"):
        return {"disabled_jargons": 0, "sanitized_jargons": 0}

    disabled_jargons = _count_ai_jargons_by_content(connection, _FOOD_ANCHOR_JARGON_CONTENTS)
    sanitized_jargons = 0
    for content in _SANITIZED_JARGON_MEANINGS:
        row = connection.exec_driver_sql(
            """
            SELECT COUNT(*)
            FROM jargons
            WHERE content = ?
              AND COALESCE(created_by, 'AI') <> 'USER'
              AND COALESCE(is_jargon, 0) = 1
              AND (
                  meaning LIKE '%饼干%'
                  OR meaning LIKE '%美食%'
                  OR meaning LIKE '%甜品%'
                  OR meaning LIKE '%冰淇淋%'
                  OR meaning LIKE '%食物%'
              )
            """,
            (content,),
        ).fetchone()
        sanitized_jargons += int(row[0] or 0) if row is not None else 0

    return {"disabled_jargons": disabled_jargons, "sanitized_jargons": sanitized_jargons}


def _disable_ai_jargons_by_content(connection: Connection, contents: Sequence[str]) -> int:
    if not contents:
        return 0

    placeholders = _placeholders(contents)
    cursor = connection.exec_driver_sql(
        f"""
        UPDATE jargons
        SET is_jargon = 0,
            is_complete = 0,
            meaning = '',
            updated_timestamp = CURRENT_TIMESTAMP
        WHERE content IN ({placeholders})
          AND COALESCE(created_by, 'AI') <> 'USER'
          AND COALESCE(is_jargon, 0) = 1
        """,
        tuple(contents),
    )
    return int(cursor.rowcount or 0)


def _count_ai_jargons_by_content(connection: Connection, contents: Sequence[str]) -> int:
    if not contents:
        return 0

    placeholders = _placeholders(contents)
    row = connection.exec_driver_sql(
        f"""
        SELECT COUNT(*)
        FROM jargons
        WHERE content IN ({placeholders})
          AND COALESCE(created_by, 'AI') <> 'USER'
          AND COALESCE(is_jargon, 0) = 1
        """,
        tuple(contents),
    ).fetchone()
    return int(row[0] or 0) if row is not None else 0


def _cleanup_behavior_food_anchor_pollution(connection: Connection) -> dict[str, int]:
    deleted_paths = _delete_behavior_paths_with_food_anchors(connection)
    deleted_actions = _delete_behavior_text_rows_with_food_anchors(
        connection,
        table_name="behavior_actions",
        text_column="action",
        reference_table="behavior_experience_paths",
        reference_column="action_id",
    )
    deleted_outcomes = _delete_behavior_text_rows_with_food_anchors(
        connection,
        table_name="behavior_outcomes",
        text_column="outcome",
        reference_table="behavior_experience_paths",
        reference_column="outcome_id",
    )
    deleted_tags = _delete_behavior_scene_tags(connection)
    return {
        "deleted_behavior_paths": deleted_paths,
        "deleted_behavior_actions": deleted_actions,
        "deleted_behavior_outcomes": deleted_outcomes,
        "deleted_behavior_tags": deleted_tags,
    }


def _count_behavior_food_anchor_pollution(connection: Connection) -> dict[str, int]:
    return {
        "deleted_behavior_paths": _count_behavior_paths_with_food_anchors(connection),
        "deleted_behavior_actions": _count_behavior_text_rows_with_food_anchors(
            connection,
            table_name="behavior_actions",
            text_column="action",
            reference_table="behavior_experience_paths",
            reference_column="action_id",
        ),
        "deleted_behavior_outcomes": _count_behavior_text_rows_with_food_anchors(
            connection,
            table_name="behavior_outcomes",
            text_column="outcome",
            reference_table="behavior_experience_paths",
            reference_column="outcome_id",
        ),
        "deleted_behavior_tags": _count_behavior_scene_tags(connection),
    }


def _delete_behavior_paths_with_food_anchors(connection: Connection) -> int:
    if not _can_clean_behavior_paths(connection):
        return 0

    query = _build_behavior_path_food_anchor_query("DELETE")
    cursor = connection.exec_driver_sql(query, _behavior_path_food_anchor_params())
    return int(cursor.rowcount or 0)


def _count_behavior_paths_with_food_anchors(connection: Connection) -> int:
    if not _can_clean_behavior_paths(connection):
        return 0

    query = _build_behavior_path_food_anchor_query("COUNT")
    row = connection.exec_driver_sql(query, _behavior_path_food_anchor_params()).fetchone()
    return int(row[0] or 0) if row is not None else 0


def _can_clean_behavior_paths(connection: Connection) -> bool:
    return (
        _has_table(connection, "behavior_experience_paths")
        and _has_table(connection, "behavior_actions")
        and _has_table(connection, "behavior_outcomes")
    )


def _build_behavior_path_food_anchor_query(mode: str) -> str:
    if mode == "DELETE":
        select_prefix = "DELETE FROM behavior_experience_paths WHERE id IN (SELECT p.id"
        suffix = ")"
    elif mode == "COUNT":
        select_prefix = "SELECT COUNT(*)"
        suffix = ""
    else:
        raise ValueError(f"未知行为路径清理模式: {mode}")

    conditions = _food_like_conditions(
        ("a.action", "o.outcome", "p.evidence_list", "p.feedback_list"),
    )
    return f"""
        {select_prefix}
        FROM behavior_experience_paths p
        LEFT JOIN behavior_actions a ON a.id = p.action_id
        LEFT JOIN behavior_outcomes o ON o.id = p.outcome_id
        WHERE {conditions}
        {suffix}
    """


def _delete_behavior_text_rows_with_food_anchors(
    connection: Connection,
    *,
    table_name: str,
    text_column: str,
    reference_table: str,
    reference_column: str,
) -> int:
    if not _has_table(connection, table_name):
        return 0

    reference_filter = _build_unreferenced_filter(connection, reference_table, reference_column)
    cursor = connection.exec_driver_sql(
        f"""
        DELETE FROM {table_name}
        WHERE {_food_like_conditions((text_column,))}
          {reference_filter}
        """,
        _food_like_params((text_column,)),
    )
    return int(cursor.rowcount or 0)


def _count_behavior_text_rows_with_food_anchors(
    connection: Connection,
    *,
    table_name: str,
    text_column: str,
    reference_table: str,
    reference_column: str,
) -> int:
    if not _has_table(connection, table_name):
        return 0

    reference_filter = _build_unreferenced_filter(connection, reference_table, reference_column)
    row = connection.exec_driver_sql(
        f"""
        SELECT COUNT(*)
        FROM {table_name}
        WHERE {_food_like_conditions((text_column,))}
          {reference_filter}
        """,
        _food_like_params((text_column,)),
    ).fetchone()
    return int(row[0] or 0) if row is not None else 0


def _build_unreferenced_filter(connection: Connection, reference_table: str, reference_column: str) -> str:
    if not _has_table(connection, reference_table):
        return ""

    table_schema = SQLiteSchemaInspector().get_table_schema(connection, reference_table)
    if not table_schema.has_column(reference_column):
        return ""

    return (
        f"AND id NOT IN ("
        f"SELECT DISTINCT {reference_column} "
        f"FROM {reference_table} "
        f"WHERE {reference_column} IS NOT NULL"
        f")"
    )


def _delete_behavior_scene_tags(connection: Connection) -> int:
    if not _has_table(connection, "behavior_scene_tag_clusters"):
        return 0

    placeholders = _placeholders(_FOOD_ANCHOR_BEHAVIOR_TAGS)
    cursor = connection.exec_driver_sql(
        f"DELETE FROM behavior_scene_tag_clusters WHERE tag IN ({placeholders})",
        _FOOD_ANCHOR_BEHAVIOR_TAGS,
    )
    return int(cursor.rowcount or 0)


def _count_behavior_scene_tags(connection: Connection) -> int:
    if not _has_table(connection, "behavior_scene_tag_clusters"):
        return 0

    placeholders = _placeholders(_FOOD_ANCHOR_BEHAVIOR_TAGS)
    row = connection.exec_driver_sql(
        f"SELECT COUNT(*) FROM behavior_scene_tag_clusters WHERE tag IN ({placeholders})",
        _FOOD_ANCHOR_BEHAVIOR_TAGS,
    ).fetchone()
    return int(row[0] or 0) if row is not None else 0


def _food_like_conditions(columns: Sequence[str]) -> str:
    return " OR ".join(f"COALESCE({column}, '') LIKE ?" for column in columns for _ in _FOOD_ANCHOR_TERMS)


def _food_like_params(columns: Sequence[str]) -> tuple[str, ...]:
    return tuple(f"%{term}%" for _column in columns for term in _FOOD_ANCHOR_TERMS)


def _behavior_path_food_anchor_params() -> tuple[str, ...]:
    return _food_like_params(("a.action", "o.outcome", "p.evidence_list", "p.feedback_list"))


def _placeholders(items: Sequence[Any]) -> str:
    return ",".join("?" for _ in items)


def _has_table(connection: Connection, table_name: str) -> bool:
    return SQLiteSchemaInspector().table_exists(connection, table_name)
