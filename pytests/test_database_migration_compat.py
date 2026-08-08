from sqlalchemy import create_engine, inspect

from src.common.database.migrations.models import MigrationExecutionContext
from src.common.database.migrations.v37_to_v38 import migrate_v37_to_v38


def test_fork_v37_without_reply_effect_table_upgrades_to_v38() -> None:
    """旧 fork 的 v37 没有上游同版本表时，也应补齐后继续迁移。"""

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        context = MigrationExecutionContext(
            connection=connection,
            current_version=37,
            target_version=38,
            step_index=1,
            step_name="v37_to_v38",
            total_steps=1,
        )

        migrate_v37_to_v38(context)

        columns = {
            column["name"]
            for column in inspect(connection).get_columns("maisaka_reply_effects")
        }
        assert "prompt_fingerprint" in columns
        assert "request_fingerprint" in columns
