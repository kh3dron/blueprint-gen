#!/usr/bin/env python3
"""Run the finite opening with an isolated graphical player and native screenshots."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "08_live_executor"))
from session import Session, Rcon
from run_session import Driver, save, next_step
from proving_ground import SOURCE


def capture_call(session, method):
    command = '/silent-command rcon.print(helpers.table_to_json(remote.call("player-capture","' + method + '")))'
    result = session.client.execute(command)
    with (session.root / "capture-rpc.jsonl").open("a") as log:
        log.write(json.dumps({"method": method, "response": result}) + "\n")
    # Map delivery can temporarily suppress read-only RCON commands during join.
    if not result and method == "status":
        return {"attached": False}
    try:
        return json.loads(result)
    except ValueError as error:
        raise RuntimeError(f"Capture RPC {method} failed: {result!r}") from error


class SynchronizedRcon(Rcon):
    def execute(self, command):
        if not command.startswith("/silent-command "):
            raise ValueError("experiment RCON accepts Lua commands only")
        self.sequence += 1
        ident = self.sequence
        marker = f"END_{ident}"
        # Keep the marker in the same scheduled Lua command: a second RCON
        # command can overtake the first when a graphical peer is connected.
        body = command.removeprefix("/silent-command ")
        self.send(ident, 2, "/silent-command local ok,err=pcall(function() " + body +
                  f" end); if not ok then rcon.print('LUA_ERROR: '..tostring(err)) end; rcon.print('{marker}')")
        result = []
        while True:
            received, _, body = self.receive()
            if received == ident:
                result.append(body)
                joined = "".join(result)
                if marker in joined:
                    response = joined[:joined.index(marker)].strip()
                    if "LUA_ERROR:" in response:
                        raise RuntimeError(response)
                    return response


class PlayerSession(Session):
    rcon_type = SynchronizedRcon

    def artifact(self, relative):
        # Native route receipts target the attached player and are written only
        # by that client. Survey exports still target the server.
        paths = (self.output / relative, self.root / "graphical/user-data/script-output" / relative)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            for path in paths:
                if path.exists():
                    try:
                        json.loads(path.read_text())
                        return path
                    except ValueError:
                        pass
            time.sleep(.025)
        raise TimeoutError(f"Observer artifact was not written: {relative}")


class GraphicalClient:
    def __init__(self, session):
        self.session = session
        self.root = session.root / "graphical"
        self.root.mkdir()
        self.process = self.log = None
        self.output = self.root / "user-data/script-output"
        (self.root / "user-data").mkdir()
        # Requested local identity; Steam builds may use the account display name.
        # No existing local profile or authentication files are read or copied.
        (self.root / "user-data/player-data.json").write_text(json.dumps({"service-username": "AdvisorCapture"}))
        # Steam's developer launch marker prevents a relaunch that discards our
        # isolated --config. It belongs only to this disposable working directory.
        (self.root / "steam_appid.txt").write_text("427520\n")
        server_config = (session.root / "config.ini").read_text()
        read_data = next(line for line in server_config.splitlines() if line.startswith("read-data="))
        (self.root / "config.ini").write_text(
            f"[path]\n{read_data}\nwrite-data={self.root / 'user-data'}\n"
            "[general]\nlocale=en\n[graphics]\nfull-screen=false\n"
            "[other]\ncheck-updates=false\nshow-tips-and-tricks-notifications=false\n"
            "enable-steam-networking=false\nenable-blueprint-storage-cloud-sync=false\n")
        shutil.copytree(session.root / "mods", self.root / "mods")

    def start(self):
        self.log = (self.root / "client.log").open("w")
        self.process = subprocess.Popen([self.session.prefix[0], "--config", str(self.root / "config.ini"),
            "--mod-directory", str(self.root / "mods"), "--disable-audio", "--window-size", "960x640",
            "--mp-connect", f"127.0.0.1:{self.session.game_port}"], cwd=self.root,
            stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            self.check()
            status = capture_call(self.session, "status")
            if status["attached"]:
                return status
            time.sleep(.2)
        raise TimeoutError(f"Graphical player did not attach; inspect {self.root / 'client.log'}")

    def check(self):
        if self.process.poll() is not None:
            raise RuntimeError(f"Graphical client exited; inspect {self.root / 'client.log'}")

    def wait_image(self, relative):
        deadline = time.monotonic() + 20
        path = self.output / relative
        while time.monotonic() < deadline:
            self.check()
            if path.exists():
                # Screenshot encoding is asynchronous; validate the complete PNG.
                from PIL import Image
                try:
                    with Image.open(path) as im:
                        im.load()
                    return path
                except OSError:
                    pass
            time.sleep(.05)
        raise TimeoutError(f"Native screenshot was not written: {path}")

    def close(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process = None
        if self.log:
            self.log.close()
            self.log = None


class RecordedDriver(Driver):
    def __init__(self, session, graphics):
        super().__init__(session)
        self.graphics = graphics
        self.record = getattr(graphics, "record", False)

    def action(self, op, args, label):
        result = super().action(op, args, label)
        if self.record:
            boundary = capture_call(self.session, "capture")
            self.graphics.wait_image(boundary["image"])
        return result


def configure_recording(session, record):
    session.client.call({"op": "configure_trace", "mode": "full" if record else "boundaries"})
    if not record:
        capture_call(session, "disable")


def capture_boundary(session, graphics):
    if getattr(graphics, "record", False):
        frame = capture_call(session, "capture")
        graphics.wait_image(frame["image"])


def run(binary, destination, config, speed, *, record=False):
    started = time.perf_counter()
    session = PlayerSession(binary, destination, config, scenario_overlay=HERE / "integration")
    graphics = None
    try:
        session.start()
        configure_recording(session, record)
        graphics = GraphicalClient(session)
        graphics.record = record
        print("Starting isolated graphical client…", flush=True)
        attachment = graphics.start()
        save(session.root / "attachment.json", attachment)
        print("Player attached to existing character.", flush=True)
        if record:
            first = capture_call(session, "enable")
            graphics.wait_image(first["image"])
        session.client.call({"op": "speed", "speed": speed})
        driver = RecordedDriver(session, graphics)
        driver.observe()
        milestones = []
        for technology in ("steam-power", "electronics", "automation-science-pack"):
            snapshot, rules, _ = driver.observe()
            action = next_step(snapshot, rules)
            if action["kind"] != "trigger" or action["technology"] != technology:
                raise ValueError(f"Unexpected advisor instruction: {action['title']}")
            driver.milestone = technology
            save(session.root / f"plan-{technology}.json", action)
            print(action["title"], flush=True)
            driver.execute_bill(action)
            result = driver.action("research", {"technology": technology}, f"Check whether {technology} unlocked")
            driver.observe()
            milestones.append(result["outcome"]["value"])
        save(session.root / "milestones.json", milestones)
        save(session.root / "final-state.json", driver.current)
        snapshot, rules, _ = driver.observe()
        save(session.root / "next-action.json", next_step(snapshot, rules))
        from verify_player import verify_directory
        save(session.root / "verification.json", verify_directory(session.root))
        capture_boundary(session, graphics)
        save(session.root / "performance.json", {"requested_speed": speed,
            "total_wall_seconds": time.perf_counter() - started,
            "simulation_ticks": driver.current["tick"] - driver.observations[0]["state"]["tick"]})
        print(json.dumps({"crafted": driver.current["crafted"], "research": driver.current["researched"],
                          "inventory": driver.current["inventory"]}, indent=2), flush=True)
        return session.root
    finally:
        if graphics:
            graphics.close()
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factorio", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=SOURCE / "config.json")
    parser.add_argument("--speed", type=int, choices=(1, 10, 40), default=10)
    parser.add_argument("--record", action="store_true", help="encode native screenshots as GIF/MP4 after completion")
    args = parser.parse_args()
    try:
        run(args.factorio, args.out, json.loads(args.config.read_text()), args.speed, record=args.record)
        if args.record:
            from render_native import build
            print(build(args.out, args.out / "recording"))
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"player-capture: {error}\n")
