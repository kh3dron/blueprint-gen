"""Encode native screenshots into an explicitly labeled construction replay."""
from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFont


FPS = 12
CANVAS = (1600, 900)
VIEWPORT = (0, 110, 1280, 720)
BACKGROUND = "#09131e"
PANEL = "#10202d"
TEXT = "#edf4f7"
MUTED = "#96afbe"
ACCENT = "#65e0bf"


def hold_frames(seconds, fps=FPS):
    """Quantize a positive hold to whole output frames, without interpolation."""
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("frame hold duration must be positive and finite")
    return max(1, round(seconds*fps))


def project_position(position, camera, zoom, resolution=(1280, 720)):
    """Project an observed world position into the fixed native-image viewport."""
    width, height = resolution
    left, top, viewport_width, viewport_height = VIEWPORT
    scale = min(viewport_width/width, viewport_height/height)
    x = (position["x"]-camera["x"])*32*zoom+width/2
    y = (position["y"]-camera["y"])*32*zoom+height/2
    if not 0 <= x < width or not 0 <= y < height:
        return None
    return (left+(viewport_width-width*scale)/2+x*scale,
            top+(viewport_height-height*scale)/2+y*scale)


def human_phase(metadata):
    """Describe the active compiler operation rather than exposing its node ID."""
    node = metadata.get("program_node", "")
    if isinstance(node, dict):
        node = " ".join(str(node.get(k, "")) for k in ("id", "operation", "parent"))
    text = " ".join(str(v) for v in (node, metadata.get("op", ""), metadata.get("label", ""))).lower()
    if "verify" in text or "verification" in text:
        return "Verification"
    if "warmup" in text or "stabiliz" in text:
        return "Startup"
    if "wait_science" in text or "measure" in text or "sample" in text:
        return "Production"
    if "procure" in text or "gather" in text or "smelt" in text or "handcraft" in text:
        return "Procurement"
    if "reconcil" in text or "retain" in text:
        return "Check construction"
    if "walk" in text:
        return "Move to build site"
    if "place" in text or "build" in text:
        return "Construction"
    return "Prepared checkpoint"


def _font(size, bold=False):
    names = (["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if bold else
             ["/System/Library/Fonts/Supplemental/Arial.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
    for name in names:
        if Path(name).exists():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default(size=size)


class NativeVideoEncoder:
    """Stream held native frames to H.264, then derive a poster and small GIF.

    ``destination`` is an output directory. ``append`` accepts the Lua recorder's
    tick, observed position, program node, label, added_builds, and production
    counters since capture began. It never removes the source screenshot.
    """

    def __init__(self, destination, camera, zoom, resolution=(1280, 720), total_builds=158, target=10):
        self.ffmpeg = shutil.which("ffmpeg")
        if self.ffmpeg is None:
            raise RuntimeError("native video recording requires ffmpeg on PATH")
        if len(resolution) != 2 or any(type(n) is not int or n <= 0 for n in resolution):
            raise ValueError("native screenshot resolution must contain two positive integers")
        if not math.isfinite(zoom) or zoom <= 0:
            raise ValueError("native camera zoom must be positive and finite")
        self.root = Path(destination)
        self.root.mkdir(parents=True, exist_ok=True)
        self.camera, self.zoom, self.resolution = dict(camera), zoom, tuple(resolution)
        self.total_builds, self.target = total_builds, target
        self.mp4, self.poster = self.root/"replay.mp4", self.root/"poster.png"
        self.gif, self.manifest_path = self.root/"preview.gif", self.root/"recording.json"
        self.log_path = self.root/"ffmpeg.log"
        self.log = self.log_path.open("wb")
        self.process = subprocess.Popen([
            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", "1600x900",
            "-framerate", str(FPS), "-i", "pipe:0", "-an", "-c:v", "libx264",
            "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(self.mp4)], stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=self.log)
        self.frames, self.first_tick, self.last_tick = [], None, None
        self.encoded_frames, self.last_image, self.last_metadata = 0, None, None
        self.finished = False
        self.fonts = {size: _font(size) for size in (13, 15, 17, 19, 22, 26)}
        self.bold = {size: _font(size, True) for size in (15, 18, 22, 30, 34, 43)}

    def _wrapped(self, draw, text, xy, font, color=MUTED, width=270, lines=2, spacing=23):
        words, rendered = str(text).split(), []
        while words and len(rendered) < lines:
            line = words.pop(0)
            while words and draw.textlength(line+" "+words[0], font=font) <= width:
                line += " "+words.pop(0)
            if draw.textlength(line, font=font) > width:
                while line and draw.textlength(line+"…", font=font) > width:
                    line = line[:-1]
                line += "…"
            if words and len(rendered) == lines-1:
                while line and draw.textlength(line+"…", font=font) > width:
                    line = line[:-1]
                line += "…"
            rendered.append(line)
        for index, line in enumerate(rendered):
            draw.text((xy[0], xy[1]+index*spacing), line, font=font, fill=color)

    def _draw(self, native, metadata, final=None):
        frame = Image.new("RGB", CANVAS, BACKGROUND)
        width, height = self.resolution
        scale = min(VIEWPORT[2]/width, VIEWPORT[3]/height)
        size = round(width*scale), round(height*scale)
        image = native if native.size == size else native.resize(size, Image.Resampling.LANCZOS)
        frame.paste(image, (VIEWPORT[0]+(VIEWPORT[2]-size[0])//2, VIEWPORT[1]+(VIEWPORT[3]-size[1])//2))
        draw = ImageDraw.Draw(frame)
        draw.rectangle((1280, 110, 1599, 829), fill=PANEL)
        draw.line((1280, 110, 1280, 830), fill="#294454", width=2)
        draw.text((28, 18), f"Automation science · {self.target:g}/min goal", font=self.bold[34], fill=TEXT)
        draw.rounded_rectangle((28, 64, 545, 98), radius=7, fill="#183c40")
        draw.text((40, 71), "Recorded replay from prepared checkpoint", font=self.bold[18], fill=ACCENT)
        draw.text((1304, 32), "NATIVE ENGINE FRAMES", font=self.bold[15], fill=MUTED)
        draw.text((1304, 64), "12 fps · held frames", font=self.fonts[15], fill=MUTED)
        phase = "Replay complete" if final else human_phase(metadata)
        draw.text((1304, 134), "CURRENT PHASE", font=self.bold[15], fill=MUTED)
        self._wrapped(draw, phase, (1304, 163), self.bold[22], TEXT, lines=2, spacing=27)
        label = str(metadata.get("label", "Native checkpoint observation")).replace("science.", "").replace(".", " ")
        self._wrapped(draw, label, (1304, 224), self.fonts[15], lines=2, spacing=20)
        draw.line((1304, 282, 1576, 282), fill="#294454")
        draw.text((1304, 305), "CONSTRUCTION", font=self.bold[15], fill=MUTED)
        builds = int(metadata.get("added_builds", 0))
        draw.text((1304, 333), f"{builds} / {self.total_builds}", font=self.bold[43], fill=TEXT)
        draw.text((1304, 389), "observed native builds", font=self.fonts[15], fill=MUTED)
        fraction = max(0, min(1, builds/self.total_builds)) if self.total_builds else 0
        draw.rounded_rectangle((1304, 420, 1576, 430), radius=5, fill="#294454")
        if fraction:
            draw.rounded_rectangle((1304, 420, 1304+max(10, 272*fraction), 430), radius=5, fill=ACCENT)
        draw.text((1304, 463), "SCIENCE MADE", font=self.bold[15], fill=MUTED)
        draw.text((1304, 491), str(metadata.get("science_produced", 0)), font=self.bold[43], fill=TEXT)
        draw.text((1304, 547), "since recording began", font=self.fonts[15], fill=MUTED)
        draw.text((1304, 585), f"Production goal: {self.target:g} / min", font=self.bold[18], fill=ACCENT)
        elapsed = max(0, (metadata["tick"]-self.first_tick)/60)
        draw.text((1304, 627), f"Game elapsed  {int(elapsed)//60}:{int(elapsed)%60:02d}", font=self.fonts[19], fill=TEXT)
        if final:
            color = ACCENT if final["verified"] else "#f6c879"
            draw.rounded_rectangle((1298, 685, 1582, 805), radius=9, fill="#18333d")
            draw.text((1312, 700), "Replay verified" if final["verified"] else "Verification pending", font=self.bold[22], fill=color)
            if final["verified"]:
                draw.text((1312, 738), f"{final['minimum_rate']:g} packs / min", font=self.bold[22], fill=TEXT)
                draw.text((1312, 772), f"{final['windows']} measured minutes", font=self.fonts[15], fill=MUTED)
        else:
            self._wrapped(draw, "Native simulation; compiler-generated construction.", (1304, 698), self.fonts[17], lines=3)
        position = metadata.get("position")
        projected = project_position(position, self.camera, self.zoom, self.resolution) if position else None
        if projected:
            x, y = projected
            # Draw into a viewport overlay so the observation marker cannot
            # spill into the header, footer or statistics panel at an edge.
            overlay = Image.new("RGBA", (1280, 720))
            marker = ImageDraw.Draw(overlay)
            y -= 110
            marker.ellipse((x-11, y-11, x+11, y+11), outline="#061017", width=6)
            marker.ellipse((x-11, y-11, x+11, y+11), outline=ACCENT, width=3)
            marker.line((x-17, y, x+17, y), fill=ACCENT, width=2)
            marker.line((x, y-17, x, y+17), fill=ACCENT, width=2)
            caption = "Agent (observed position)"
            caption_width = marker.textlength(caption, font=self.fonts[13])+16
            tx = max(4, min(1280-caption_width-4, x+19))
            ty = max(4, min(692, y-29))
            marker.rounded_rectangle((tx, ty, tx+caption_width, ty+24), radius=4, fill="#10202de8")
            marker.text((tx+8, ty+5), caption, font=self.fonts[13], fill=TEXT)
            frame.paste(overlay, (0, 110), overlay)
        draw = ImageDraw.Draw(frame)
        draw.text((28, 844), "Construction steps; production at 20×", font=self.bold[18], fill=TEXT)
        draw.text((28, 873), "Native screenshots held between observations. No interpolated motion.", font=self.fonts[15], fill=MUTED)
        return frame

    def _write(self, frame, count):
        data = frame.tobytes()
        try:
            for _ in range(count):
                self.process.stdin.write(data)
        except (BrokenPipeError, OSError) as error:
            self.abort()
            details = self.log_path.read_text(errors="replace")[-2000:]
            raise RuntimeError("ffmpeg stopped while encoding native frames: "+details) from error
        self.encoded_frames += count

    def append(self, image_path, metadata, duration_seconds):
        if self.finished or self.process is None:
            raise RuntimeError("native video encoder is closed")
        tick = metadata.get("tick")
        if not isinstance(tick, (int, float)) or isinstance(tick, bool) or not math.isfinite(tick):
            raise ValueError("native recording metadata requires a finite tick")
        if self.last_tick is not None and tick < self.last_tick:
            raise ValueError("native recording ticks moved backwards")
        count = hold_frames(duration_seconds)
        path = Path(image_path)
        with Image.open(path) as source:
            if source.size != self.resolution:
                raise ValueError(f"native screenshot has size {source.size}; expected {self.resolution}")
            native = source.convert("RGB")
        if self.first_tick is None:
            self.first_tick = tick
        self.last_tick, self.last_image, self.last_metadata = tick, native, deepcopy(metadata)
        frame = self._draw(native, metadata)
        entry = {"frame": metadata.get("frame", len(self.frames)), "native_image": path.name,
                 "sha256": sha256(path.read_bytes()).hexdigest(), "tick": tick,
                 "position": deepcopy(metadata.get("position")), "op": metadata.get("op"),
                 "program_node": deepcopy(metadata.get("program_node")), "label": metadata.get("label"),
                 "added_builds": metadata.get("added_builds", 0),
                 "science_produced": metadata.get("science_produced", 0),
                 "requested_duration_seconds": duration_seconds,
                 "duration_seconds": count/FPS, "encoded_frames": count}
        self._write(frame, count)
        self.frames.append(entry)
        return entry

    def finish(self, verification=None):
        if self.finished or self.last_image is None:
            raise RuntimeError("native video finish requires an open recording with a frame")
        verification = deepcopy(verification) if verification is not None else None
        evidence = verification or {}
        rates = evidence.get("science_per_minute", evidence.get("measured_per_minute", []))
        passed = (evidence.get("automatic_science_observed") is True
                  or evidence.get("science_goal_complete") is True or evidence.get("status") == "observed-complete")
        verified = bool(passed and rates and min(rates) >= self.target)
        final = {"verified": verified, "minimum_rate": min(rates) if rates else None, "windows": len(rates)}
        frame = self._draw(self.last_image, self.last_metadata, final)
        self._write(frame, hold_frames(2))
        frame.save(self.poster)
        self.process.stdin.close()
        try:
            code = self.process.wait(timeout=60)
        except subprocess.TimeoutExpired as error:
            self.abort()
            raise RuntimeError("ffmpeg did not finish the native video") from error
        self.log.close()
        self.process = None
        self.finished = True
        if code:
            raise RuntimeError("ffmpeg native video failed: "+self.log_path.read_text(errors="replace")[-2000:])
        # Palette generation and use stay within one bounded ffmpeg pipeline.
        subprocess.run([self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(self.mp4),
                        "-filter_complex", "fps=6,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3",
                        "-loop", "0", str(self.gif)], check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, timeout=60)
        manifest = {"schema_version": 1, "kind": "native-recorded-replay", "label": "Recorded replay from prepared checkpoint",
                    "camera": self.camera, "zoom": self.zoom, "native_resolution": list(self.resolution),
                    "output_resolution": list(CANVAS), "fps": FPS, "gif_fps": 6,
                    "target_per_minute": self.target, "total_builds": self.total_builds,
                    "timing": "Held native construction frames; production at 20x; no interpolated motion",
                    "first_tick": self.first_tick, "last_tick": self.last_tick,
                    "encoded_frames": self.encoded_frames, "duration_seconds": self.encoded_frames/FPS,
                    "final_hold_seconds": 2, "native_frames": self.frames, "verification": verification,
                    "verified_replay": verified,
                    "artifacts": {"mp4": self.mp4.name, "gif": self.gif.name, "poster": self.poster.name}}
        self.manifest_path.write_text(json.dumps(manifest, indent=2)+"\n")
        return {"mp4": str(self.mp4), "gif": str(self.gif), "poster": str(self.poster),
                "manifest": str(self.manifest_path), "verified_replay": verified,
                "native_frames": len(self.frames), "duration_seconds": self.encoded_frames/FPS}

    def abort(self):
        """Close and reap ffmpeg after a failed replay; leave diagnostics on disk."""
        if self.process is not None:
            try:
                if self.process.stdin and not self.process.stdin.closed:
                    self.process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            self.process = None
        if not self.log.closed:
            self.log.close()
        self.finished = True
