"""Compose the science observer around the unchanged prerequisite controller."""
from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile

from ..legacy import iron_overlay, ROOT


@contextmanager
def science_overlay(record=False):
    with iron_overlay() as base, tempfile.TemporaryDirectory(prefix="constructor-science-overlay-") as temp:
        overlay = Path(temp)
        for path in base.glob("*.lua"):
            name = {"extension.lua": "iron.lua", "adapter.lua": "iron_adapter.lua"}.get(path.name, path.name)
            shutil.copy2(path, overlay / name)
        for name, target in (("science.lua", "extension.lua"), ("science_adapter.lua", "adapter.lua"),
                             ("science_walking.lua", "science_walking.lua"), ("science_control.lua", "control.lua")):
            shutil.copy2(Path(__file__).parent / name, overlay / target)
        controller = overlay / "live.lua"
        source = (ROOT / "08_live_executor/integration/control.lua").read_text()
        marker = "  local s=state()\n  s.frame=storage.frame;s.event=event;"
        if source.count(marker) != 1:
            raise ValueError("native trace hook no longer matches the prerequisite controller")
        controller.write_text(source.replace(marker,
            "  local s=extension.trace and extension.trace(event) or state()\n  s.frame=storage.frame;s.event=event;"))
        if record:
            shutil.copy2(Path(__file__).parent / "native_recording.lua", overlay / "native_recording.lua")
            control = overlay / "control.lua"
            control.write_text(control.read_text() + '\nrequire("native_recording")\n')
        yield overlay
