from pathlib import Path
from scripts import build_napcat

import pytest


@pytest.mark.parametrize("has_webui", [False, True])
def test_build_checks_webui_before_replacing_runtime(tmp_path: Path, monkeypatch, has_webui: bool) -> None:
    source = tmp_path / "source"
    output = tmp_path / "runtime"
    (output / "config").mkdir(parents=True)
    config = output / "config" / "settings.json"
    config.write_bytes(b'{"account":"local-test"}')
    marker = output / "old-runtime.txt"
    marker.write_bytes(b"old-runtime")
    (source / "packages" / "napcat-shell-loader").mkdir(parents=True)
    commands = []

    def run(command, cwd):
        commands.append(command)
        if has_webui and command[-1] == "build:shell":
            index = source / "packages" / "napcat-shell" / "dist" / "static" / "index.html"
            index.parent.mkdir(parents=True)
            index.write_bytes(b"<html>test</html>")

    monkeypatch.setattr(build_napcat, "ensure_source", lambda path: None)
    monkeypatch.setattr(build_napcat, "ensure_toolchain", lambda: ("node", "pnpm"))
    monkeypatch.setattr(build_napcat, "run", run)
    monkeypatch.setattr("sys.argv", [
        "build_napcat", "--source", str(source), "--output", str(output),
        "--clean", "--no-install", "--no-runtime-deps",
    ])
    if has_webui:
        assert build_napcat.main() == 0
        assert (output / "static" / "index.html").read_bytes() == b"<html>test</html>"
        assert not marker.exists()
    else:
        with pytest.raises(SystemExit, match="WebUI build artifact missing"):
            build_napcat.main()
        assert marker.read_bytes() == b"old-runtime"
    assert config.read_bytes() == b'{"account":"local-test"}'
    assert not output.with_name("runtime.preserved").exists()
    assert commands == [["pnpm", "run", "build:webui"], ["pnpm", "run", "build:shell"]]
