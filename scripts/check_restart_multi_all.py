from pathlib import Path
from tempfile import TemporaryDirectory

import os
import shutil
import subprocess


def check() -> None:
    source = Path(__file__).resolve().parent.parent / "restart-multi-all.bat"
    for stop_exit, start_exit, expected_exit, expected_calls in (
        (0, 0, 0, ["stop", "start"]),
        (7, 0, 7, ["stop"]),
        (0, 9, 9, ["stop", "start"]),
    ):
        with TemporaryDirectory(prefix="multi bot restart ") as directory:
            root = Path(directory)
            shutil.copy2(source, root / source.name)
            for name, exit_code in (("stop", stop_exit), ("start", start_exit)):
                content = f'@echo off\r\necho {name}>>"%~dp0calls.txt"\r\nexit /b {exit_code}\r\n'
                (root / f"{name}-multi-bot.bat").write_bytes(content.encode("ascii"))
            result = subprocess.run(
                [os.environ["COMSPEC"], "/d", "/c", "call", str(root / source.name)],
                cwd=root, capture_output=True, timeout=10,
            )
            assert result.returncode == expected_exit, (result.returncode, result.stderr)
            assert (root / "calls.txt").read_text().splitlines() == expected_calls
    print("PASS: stop/start order, stop failure abort, start exit propagation, paths with spaces")


if __name__ == "__main__":
    check()
