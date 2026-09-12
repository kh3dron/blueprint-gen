"""Local-only disposable Factorio server and standard-library Source RCON client."""
import json
from pathlib import Path
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "05_advisor_experiment"))
sys.path.insert(0, str(ROOT / "05_advisor_experiment/tools"))
from build_observer import build as build_observer, lua
from proving_ground import build as build_ground


class Rcon:
    def __init__(self, port, password):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.sequence = 1
        try:
            self.send(1, 3, password)
            while True:
                ident, kind, _ = self.receive()
                if ident == -1:
                    raise RuntimeError("RCON authentication failed")
                if ident == 1 and kind == 2:
                    break
        except BaseException:
            self.close()
            raise

    def close(self):
        self.socket.close()

    def exact(self, count):
        data = bytearray()
        while len(data) < count:
            part = self.socket.recv(count - len(data))
            if not part:
                raise ConnectionError("RCON disconnected")
            data.extend(part)
        return bytes(data)

    def send(self, ident, kind, body):
        payload = struct.pack("<ii", ident, kind) + body.encode() + b"\0\0"
        self.socket.sendall(struct.pack("<i", len(payload)) + payload)

    def receive(self):
        size = struct.unpack("<i", self.exact(4))[0]
        if not 10 <= size <= 16 * 1024 * 1024:
            raise RuntimeError("Invalid RCON packet size")
        packet = self.exact(size)
        if packet[-2:] != b"\0\0":
            raise RuntimeError("Invalid RCON packet terminator")
        return (*struct.unpack("<ii", packet[:8]), packet[8:-2].decode())

    def execute(self, command):
        self.sequence += 2
        ident = self.sequence
        self.send(ident, 2, command)
        # A second command delimits even multipart responses, without guessing
        # packet sizes or mistaking a partial JSON response for the whole result.
        marker = f"END_{ident}"
        self.send(ident + 1, 2, f"/silent-command rcon.print('{marker}')")
        result = []
        while True:
            received, _, body = self.receive()
            if received == ident + 1 and marker in body:
                return "".join(result).strip()
            if received == ident:
                result.append(body)

    def call(self, request):
        command = '/silent-command rcon.print(helpers.table_to_json(remote.call("opening-executor","call",' + lua(request) + ")) )"
        result = json.loads(self.execute(command))
        if result.get("ok") is not True:
            raise RuntimeError(result.get("error", "executor refused the request"))
        return result["value"]


def free_port(kind):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Session:
    rcon_type = Rcon
    observer_builder = staticmethod(build_observer)

    def __init__(self, binary, destination, config, *, scenario_overlay=None, checkpoint=None):
        self.root = Path(destination).resolve()
        self.root.mkdir(parents=True, exist_ok=False)
        self.process = self.client = self.log = None
        self.starts = 0
        self.password = secrets.token_hex(16)
        binary = Path(binary).resolve()
        data = next((p / "data" for p in list(binary.parents)[:4] if (p / "data/core").is_dir()), None)
        if data is None:
            raise ValueError("Cannot find Factorio installation data")
        mod = self.observer_builder(self.root / "mods")
        scenario = build_ground(config, mod / "scenarios/live-opening")
        for source in (Path(__file__).parent / "integration").glob("*.lua"):
            shutil.copy2(source, scenario / source.name)
        shutil.copy2(ROOT / "07_bootstrap_executor/integration/adapter.lua", scenario / "adapter.lua")
        if scenario_overlay is not None:
            # Extensions wrap the live controller without editing the baseline.
            shutil.copy2(scenario / "control.lua", scenario / "live.lua")
            for source in Path(scenario_overlay).glob("*.lua"):
                shutil.copy2(source, scenario / source.name)
        packages = [json.loads(p.read_text())["name"] for p in data.glob("*/info.json")]
        (self.root / "mods/mod-list.json").write_text(json.dumps({"mods": [
            {"name": n, "enabled": n == "base"} for n in packages if n != "core"
        ] + [{"name": "blueprint-gen-observer", "enabled": True}]}))
        (self.root / "config.ini").write_text(f"[path]\nread-data={data}\nwrite-data={self.root / 'user-data'}\n")
        self.prefix = [str(binary), "--config", str(self.root / "config.ini"), "--mod-directory", str(self.root / "mods")]
        settings = json.loads((data / "server-settings.example.json").read_text())
        settings.update({"name": "Disposable advisor experiment", "visibility": {"public": False, "lan": False},
                    "require_user_verification": False, "allow_commands": "true", "auto_pause": False,
                    "autosave_interval": 0, "non_blocking_saving": False})
        (self.root / "server-settings.json").write_text(json.dumps(settings))
        (self.root / "world-config.json").write_text(json.dumps(config, indent=2) + "\n")
        if checkpoint is not None:
            from checkpoint import rewrite_scenario
            # Loading an external save skips scenario creation, which normally
            # creates this directory before later game.server_save calls.
            (self.root / "user-data/saves").mkdir(parents=True, exist_ok=True)
            self.save = self.root / "resume.zip"
            rewrite_scenario(Path(checkpoint) / "game.zip", self.save, scenario)
            return
        result = subprocess.run(self.prefix + ["--scenario2map", "blueprint-gen-observer/live-opening"],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        (self.root / "create.log").write_text(result.stdout)
        if result.returncode:
            raise RuntimeError(f"Scenario creation failed; inspect {self.root / 'create.log'}")
        saves = list((self.root / "user-data/saves").rglob("*.zip"))
        if len(saves) != 1:
            raise RuntimeError("Expected one new scenario save")
        self.save = saves[0]

    def start(self, save=None):
        self.starts += 1
        self.log = (self.root / f"server-{self.starts}.log").open("w")
        port = free_port(socket.SOCK_STREAM)
        self.game_port = free_port(socket.SOCK_DGRAM)
        self.process = subprocess.Popen(self.prefix + ["--start-server", str(save or self.save),
            "--bind", "127.0.0.1", "--port", str(self.game_port),
            "--rcon-bind", f"127.0.0.1:{port}", "--rcon-password", self.password,
            "--server-settings", str(self.root / "server-settings.json")],
            stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 30
        try:
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError(f"Factorio server exited; inspect {self.root / f'server-{self.starts}.log'}")
                try:
                    self.client = self.rcon_type(port, self.password)
                    return
                except (ConnectionRefusedError, TimeoutError):
                    time.sleep(.05)
            raise TimeoutError("Factorio server did not open its RCON port")
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.client:
            self.client.close()
            self.client = None
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

    @property
    def output(self):
        return self.root / "user-data/script-output"

    def artifact(self, relative):
        return self.output / relative
