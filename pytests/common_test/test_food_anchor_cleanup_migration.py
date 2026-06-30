from sqlmodel import create_engine

from src.common.database.migrations.models import MigrationExecutionContext
from src.common.database.migrations.v34_to_v35 import (
    cleanup_food_anchor_learning_pollution_dry_run as migration_dry_run,
    migrate_v34_to_v35,
)


def test_v34_to_v35_cleans_food_anchor_jargons_and_behavior_refs() -> None:
    engine = create_engine("sqlite://")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE jargons (
                id INTEGER NOT NULL,
                content VARCHAR(255) NOT NULL,
                evidence_messages TEXT,
                meaning TEXT NOT NULL,
                session_id_dict TEXT NOT NULL,
                count INTEGER NOT NULL,
                is_jargon BOOLEAN,
                is_complete BOOLEAN NOT NULL,
                is_global BOOLEAN NOT NULL,
                last_inference_count INTEGER NOT NULL,
                created_timestamp DATETIME,
                updated_timestamp DATETIME,
                created_by VARCHAR(6) NOT NULL,
                PRIMARY KEY (id)
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO jargons (
                id, content, evidence_messages, meaning, session_id_dict, count,
                is_jargon, is_complete, is_global, last_inference_count,
                created_timestamp, updated_timestamp, created_by
            )
            VALUES
                (1, '小饼干', NULL, '饼干奖励', '{}', 4, 1, 0, 1, 0, NULL, NULL, 'AI'),
                (2, '痒痒', NULL, '通过挠痒换饼干的互动', '{}', 9, 1, 0, 1, 0, NULL, NULL, 'AI'),
                (3, '小饼干', NULL, '用户手动保留', '{}', 1, 1, 0, 1, 0, NULL, NULL, 'USER'),
                (4, '普通黑话', NULL, '正常含义', '{}', 1, 1, 0, 1, 0, NULL, NULL, 'AI')
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE behavior_actions (
                id INTEGER PRIMARY KEY,
                action TEXT NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE behavior_outcomes (
                id INTEGER PRIMARY KEY,
                outcome TEXT NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE behavior_experience_paths (
                id INTEGER PRIMARY KEY,
                action_id INTEGER,
                outcome_id INTEGER,
                evidence_list TEXT,
                feedback_list TEXT
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE behavior_scene_tag_clusters (
                id INTEGER PRIMARY KEY,
                tag_kind TEXT NOT NULL,
                tag TEXT NOT NULL,
                cluster_key TEXT NOT NULL,
                source_count INTEGER NOT NULL DEFAULT 0,
                update_time TEXT
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO behavior_actions (id, action)
            VALUES
                (1, '用承诺明天做美食作为奖励'),
                (2, '跟随当前话题自然回应')
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO behavior_outcomes (id, outcome)
            VALUES
                (1, '对方接受饼干奖励'),
                (2, '对话自然收尾')
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO behavior_experience_paths (id, action_id, outcome_id, evidence_list, feedback_list)
            VALUES
                (10, 1, 1, '提到小熊饼干', '继续做饭话题'),
                (11, 2, 2, '讨论训练', '自然收尾')
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO behavior_scene_tag_clusters (id, tag_kind, tag, cluster_key, source_count, update_time)
            VALUES
                (20, 'domain', '做饼干', 'tc_food', 1, '2026-06-30'),
                (21, 'domain', '训练', 'tc_training', 1, '2026-06-30')
            """
        )

        migrate_v34_to_v35(
            MigrationExecutionContext(
                connection=connection,
                current_version=34,
                target_version=35,
                step_index=1,
                step_name="v34_to_v35",
                total_steps=1,
            )
        )

        jargons = connection.exec_driver_sql(
            "SELECT id, is_jargon, meaning FROM jargons ORDER BY id"
        ).mappings().all()
        action_ids = connection.exec_driver_sql("SELECT id FROM behavior_actions ORDER BY id").mappings().all()
        outcome_ids = connection.exec_driver_sql("SELECT id FROM behavior_outcomes ORDER BY id").mappings().all()
        path_ids = connection.exec_driver_sql("SELECT id FROM behavior_experience_paths ORDER BY id").mappings().all()
        tag_ids = connection.exec_driver_sql("SELECT id FROM behavior_scene_tag_clusters ORDER BY id").mappings().all()
        remaining_cleanup_count = sum(migration_dry_run(connection).values())

    assert jargons[0]["is_jargon"] == 0
    assert jargons[0]["meaning"] == ""
    assert jargons[1]["is_jargon"] == 1
    assert "饼干" not in jargons[1]["meaning"]
    assert "食物" not in jargons[1]["meaning"]
    assert jargons[2]["is_jargon"] == 1
    assert jargons[2]["meaning"] == "用户手动保留"
    assert [row["id"] for row in action_ids] == [2]
    assert [row["id"] for row in outcome_ids] == [2]
    assert [row["id"] for row in path_ids] == [11]
    assert [row["id"] for row in tag_ids] == [21]
    assert remaining_cleanup_count == 0
