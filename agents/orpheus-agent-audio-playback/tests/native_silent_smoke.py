"""Exercise macOS CoreAudio with Orpheus's native afplay subprocess path."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import wave
from pathlib import Path
from types import SimpleNamespace

from orpheus_common.audio.playback import SubprocessAudioPlayer


async def _play(path: Path) -> None:
    player = SubprocessAudioPlayer(
        config=SimpleNamespace(audio=SimpleNamespace(playback_command="afplay"))
    )
    await player.play(path)
    if not await player.wait():
        raise RuntimeError("afplay did not complete the silent playback")


def main() -> int:
    if sys.platform != "darwin":
        print("This silent native playback smoke test requires macOS.", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="orpheus-afplay-smoke-") as temp_dir:
        path = Path(temp_dir) / "silence.wav"
        with wave.open(str(path), "wb") as sound:
            sound.setnchannels(1)
            sound.setsampwidth(2)
            sound.setframerate(8000)
            sound.writeframes(b"\x00\x00" * 1600)  # 200 ms of digital silence
        asyncio.run(_play(path))

    print("Orpheus afplay/CoreAudio silent playback completed (200 ms).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
