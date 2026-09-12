"""Opt-in native capture that drains temporary frames after each player action."""
import json
import re
import shutil

from ..verify_science import all_entities
from .render_recording import NativeVideoEncoder


def camera_for(program, opening, resolution=(1280, 720)):
    entities = list(all_entities({"entities": [], "iron": opening["state"]["iron"]}).values())
    entities += program["design"]["placements"]
    xs, ys = ([e["position"][key] for e in entities] for key in ("x", "y"))
    width, height = max(xs) - min(xs) + 10, max(ys) - min(ys) + 10
    camera = {"x": (max(xs) + min(xs)) / 2, "y": (max(ys) + min(ys)) / 2}
    zoom = round(min(.8, resolution[0] / (32 * width), resolution[1] / (32 * height)), 4)
    return camera, zoom


class NativeRecorder:
    def __init__(self, driver, graphics, program):
        self.driver, self.graphics = driver, graphics
        self.session = driver.session
        self.destination = driver.root / "recording"
        self.trace = self.session.output / "constructor-video.jsonl"
        self.frame_count = self.offset = 0
        self.finished = False
        self.original_action = driver.action
        camera, zoom = camera_for(program, driver.observations[-1])
        self.settings = {"camera": camera, "zoom": zoom, "resolution": [1280, 720],
                         "interval_ticks": 300,
                         "goal": f"Automate {program['goal']['per_minute']:g} {program['goal']['item']}/min",
                         "item": program["goal"]["item"], "target": program["goal"]["per_minute"],
                         "total_builds": len(program["change"]["add"])}
        self.encoder = NativeVideoEncoder(self.destination, camera, zoom,
            total_builds=self.settings["total_builds"], target=self.settings["target"])

    def call(self, method, args=None):
        # JSON is converted to Lua by the same audited serializer used by the
        # prerequisite RCON client, never interpolated as executable source.
        from session import lua
        arguments = "," + lua(args) if args is not None else ""
        command = ('/silent-command rcon.print(helpers.table_to_json(remote.call('
                   '"constructor-recording","' + method + '"' + arguments + ')))')
        return json.loads(self.session.client.execute(command))

    def start(self):
        self.call("configure", self.settings)
        self.call("capture")
        self.drain(initial=True)
        self.driver.action = self.action
        print("Recording native checkpoint replay; temporary frames are encoded and removed.", flush=True)

    def action(self, op, args, label):
        result = self.original_action(op, args, label)
        if (op == "walk_science" or op == "wait_science"
                or (op == "place_science" and result["outcome"]["value"].get("added"))):
            self.call("capture")
        self.drain()
        return result

    def drain(self, *, initial=False):
        if not self.trace.exists():
            return
        with self.trace.open() as stream:
            stream.seek(self.offset)
            lines = stream.readlines()
            self.offset = stream.tell()
        for line in lines:
            frame = json.loads(line)
            relative = frame["image"]
            if not re.fullmatch(r"constructor-video/frame-[0-9]{6}\.png", relative):
                raise ValueError("invalid native recording image path")
            if frame["frame"] != self.frame_count + 1:
                raise ValueError("native recording frame sequence has a gap")
            path = self.graphics.wait_image(relative)
            if initial and self.frame_count == 0:
                shutil.copy2(path, self.destination / "first-frame.png")
            duration = 1.5 if self.frame_count == 0 else .25 if frame.get("op") == "wait_science" else .12
            self.encoder.append(path, frame, duration)
            path.unlink()
            self.frame_count += 1

    def finish(self, verification):
        self.call("capture")
        self.call("disable")
        self.drain()
        self.encoder.finish(verification)
        self.finished = True

    def close(self):
        self.driver.action = self.original_action
        if not self.finished:
            self.encoder.abort()
