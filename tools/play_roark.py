"""Play the supplied gym save using only screenshots and controller input.

This is a development scene driver, never part of the iOS package. OCR helps
advance menus but cannot certify a rendering pass; a person must inspect the
saved final-present captures and make the separate validation verdict.
"""
import json
from pathlib import Path
import re
import subprocess
import time

FIGHT = "\u6218\u6597"
RUN = "\u9003\u8d70"
PARTY = "\u5b9d\u53ef\u68a6"
CHIMCHAR = "\u5c0f\u706b\u7130\u7334"
PUNCH = "\u589e\u5f3a\u62f3"
EMBER = "\u706b\u82b1"
POTION = "\u4f24\u836f"
USE = "\u4f7f\u7528"
CHANGE = "\u66f4\u6362"
BADGE = "\u5fbd\u7ae0"


def play(root, evidence, process, command, pause, upload, publish_status):
    observer = evidence / "read-game-frame"
    subprocess.run(["clang", "-O2", "-fobjc-arc", str(Path(__file__).with_name("read_game_frame.m")),
                    "-framework", "Foundation", "-framework", "AppKit", "-framework", "Vision",
                    "-o", str(observer)], check=True)
    frames = evidence / "autoplay"
    frames.mkdir(exist_ok=True)
    began = time.monotonic()
    actions = []
    index = 0
    switched = False
    healing = False
    item_applied = False
    badge_seen = False
    battle_seen = False
    heal_streak = 0
    previous = None
    same = 0
    result = {"verdict": "pending", "mode": "controller and final-present OCR",
              "memory_changes": False, "human_visual_verdict_required": True}

    def key(name, hold=1, wait=4):
        command(name + "~" + str(hold))
        pause(hold + wait)

    def observe():
        nonlocal index
        index += 1
        path = frames / f"frame-{index:04d}.png"
        command("shot " + str(path))
        until = time.monotonic() + 35
        size = 0
        while time.monotonic() < until and process.poll() is None:
            current = path.stat().st_size if path.exists() else 0
            if current > 100 and current == size:
                break
            size = current
            time.sleep(.3)
        else:
            raise RuntimeError("No final-present frame completed within the existing capture window")
        data = json.loads(subprocess.check_output([str(observer), str(path)], timeout=30))
        data["capture"] = path.name
        (path.with_suffix(".json")).write_text(json.dumps(data, indent=2) + "\n")
        return data, path

    def save_status(state, path, **values):
        entry = {"elapsed": round(time.monotonic() - began, 2), "state": state,
                 "capture": path.name, **values}
        actions.append(entry)
        (evidence / "autoplay-actions.json").write_text(json.dumps(actions, indent=2) + "\n")
        (evidence / "autoplay-status.json").write_text(json.dumps(entry, indent=2) + "\n")
        upload(evidence / "autoplay-status.json")
        # Publish every decision frame privately for independent visual review.
        public_name = evidence / "shots" / ("auto-" + path.name)
        public_name.write_bytes(path.read_bytes())
        upload(public_name)
        print("Scene driver: observation saved privately", flush=True)
        publish_status()

    def fraction(data, left=True):
        lines = [v for v in data["lines"] if (v["x"] < .34 if left else v["x"] > .70)
                 and (v["y"] > .85 if left else v["y"] < .20)]
        for line in lines:
            match = re.fullmatch(r"\s*(\d{1,3})\s*[/|]\s*(\d{1,3})\s*", line["text"])
            if match:
                value, maximum = map(int, match.groups())
                if 0 <= value <= maximum <= 999:
                    return value, maximum
        return None

    def select_party(data, target=4):
        # The supplied save has Chimchar in slot five. Confirm the highlighted
        # border after every direction; missed frames cannot silently select a
        # different party member.
        for _ in range(16):
            scores = data["party"]
            if max(scores) < 8:
                pause(5)
            else:
                selected = max(range(6), key=scores.__getitem__)
                if selected == target:
                    return data
                key("Down" if selected < target else "Up", .5, 3)
            data, _ = observe()
        raise RuntimeError("Could not confirm the target party slot")

    def choose_punch(data):
        for _ in range(12):
            scores = data["moves"]
            if max(scores) < 4:
                pause(5)
            else:
                selected = max(range(4), key=scores.__getitem__)
                if selected == 3:
                    key("A", 1, 20)
                    return
                key("Down", .5, 3)
            data, _ = observe()
        raise RuntimeError("Could not confirm Power-Up Punch selection")

    def choose_main(data, target):
        for _ in range(12):
            scores = data["main"]
            if max(scores) < 4:
                pause(5)
            else:
                selected = max(range(4), key=scores.__getitem__)
                if selected == target:
                    key("A", 1, 8)
                    return
                key("Down" if selected < target else "Up", .5, 3)
            data, _ = observe()
        raise RuntimeError("Could not confirm battle menu selection")

    try:
        # The original save boots through the same unmodified title/load menu.
        pause(100)
        key("A", 1, 10)
        key("A", 1, 110)
        key("LUp", 15, 5)
        key("A", 1, 8)
        for _ in range(500):
            if process.poll() is not None:
                raise RuntimeError("Game process exited during scene playback")
            if time.monotonic() - began > 180 * 60:
                raise RuntimeError("Automatic scene playback time budget exhausted")
            data, path = observe()
            lines = data["lines"]
            text = "\n".join(v["text"] for v in lines)
            flat = re.sub(r"\s", "", text)
            signature = re.sub(r"\d", "", flat)
            same = same + 1 if signature == previous else 0
            previous = signature
            main = FIGHT in flat and RUN in flat
            moves = PUNCH in flat and EMBER in flat
            party_screen = sum(bool(re.search(r"\d+\s*/\s*\d+", v["text"])) for v in lines if v["x"] < .35) >= 3
            low_dialog = any(v["x"] > .15 and v["y"] > .72 and
                             len(re.sub(r"[\d\s/]+", "", v["text"])) > 5 for v in lines)
            if BADGE in flat and battle_seen and any(word in flat for word in
                    ("\u5f97\u5230", "\u83b7\u5f97")):
                badge_seen = True
                save_status("badge-dialog", path, text=text)
                key("A", 1, 12)
            elif main:
                battle_seen = True
                hp = fraction(data)
                save_status("battle-menu", path, hp=hp, switched=switched, heal_streak=heal_streak, text=text)
                healing = False
                item_applied = False
                if not switched:
                    choose_main(data, 1)
                elif hp is None:
                    if same > 3:
                        raise RuntimeError("Cannot safely read active HP")
                    pause(8)
                elif hp[0] == 0:
                    raise RuntimeError("Active party member fainted; manual battle review required")
                elif hp[0] <= 18 and heal_streak < 5:
                    # Bag is the third battle option. Navigation from the
                    # top is bounded; the next frame must confirm the bag.
                    choose_main(data, 2)
                    healing = True
                else:
                    heal_streak = 0
                    choose_main(data, 0)
            elif moves:
                save_status("move-menu", path, text=text, scores=data["moves"])
                choose_punch(data)
            elif party_screen:
                save_status("party-menu", path, healing=healing, scores=data["party"], text=text)
                if healing and item_applied:
                    key("A", 1, 20)
                    continue
                data = select_party(data)
                key("A", 1, 5)
                if healing:
                    key("A", 1, 20)
                    item_applied = True
                    heal_streak += 1
                else:
                    key("A", 1, 25)
                    switched = True
            elif healing and POTION in flat:
                save_status("bag-menu", path, text=text)
                key("A", 1, 5)
                key("A", 1, 6)
            elif healing and USE in flat:
                save_status("item-command", path, text=text)
                key("A", 1, 6)
            elif CHANGE in flat and battle_seen and not main and not party_screen:
                save_status("opponent-change-dialog", path, text=text)
                key("B", 1, 15)
            elif badge_seen and not low_dialog and not main and not moves and not party_screen:
                save_status("post-badge-candidate", path, text=text)
                result.update(verdict="ready for human review", badge_dialog_seen=True,
                              final_capture="auto-" + path.name)
                break
            else:
                save_status("animation-or-dialog", path, text=text)
                if same > 16:
                    raise RuntimeError("Scene did not advance; preserve process for inspection")
                # A advances ordinary text; it does not dismiss a battle menu
                # until the next observation has classified that menu.
                key("A", 1, 8 if low_dialog else 15)
        else:
            raise RuntimeError("Scene observation budget exhausted")
    except (RuntimeError, subprocess.SubprocessError, ValueError) as error:
        result.update(verdict="manual review required", reason=str(error))
    finally:
        result["elapsed"] = round(time.monotonic() - began, 2)
        (evidence / "autoplay-result.json").write_text(json.dumps(result, indent=2) + "\n")
        upload(evidence / "autoplay-result.json")
        upload(evidence / "autoplay-actions.json")
        archive = evidence / "autoplay-evidence.zip"
        import shutil
        shutil.make_archive(str(archive.with_suffix("")), "zip", frames)
        upload(archive)
        print("Scene driver result:", json.dumps(result), flush=True)
    return result
