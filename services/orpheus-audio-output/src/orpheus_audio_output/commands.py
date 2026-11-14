"""Bounded external commands (bluetoothctl, pactl), optionally as another user."""

from __future__ import annotations

import os
import pwd
import subprocess
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    output: str  # stdout and stderr, interleaved
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


@dataclass(frozen=True)
class RunAs:
    """Identity and environment for commands run as the audio server's user."""

    user: str
    uid: int
    gid: int
    home: str

    @classmethod
    def for_user(cls, user: str) -> RunAs:
        entry = pwd.getpwnam(user)  # KeyError when the user does not exist
        return cls(user=user, uid=entry.pw_uid, gid=entry.pw_gid, home=entry.pw_dir)


class CommandRunner:
    """Runs commands with a hard timeout. Never feeds stdin (bluetoothctl in
    interactive mode appends every command to an unbounded history file)."""

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float,
        run_as: Optional[RunAs] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> CommandResult:
        kwargs: dict = {}
        if run_as is not None and os.geteuid() != run_as.uid:
            kwargs.update(user=run_as.uid, group=run_as.gid, extra_groups=_groups_of(run_as))
        try:
            proc = subprocess.run(
                list(argv),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                env=dict(env) if env is not None else None,
                check=False,
                **kwargs,
            )
        except subprocess.TimeoutExpired as exc:
            out = exc.output.decode(errors="replace") if isinstance(exc.output, bytes) else ""
            return CommandResult(returncode=124, output=out, timed_out=True)
        except (FileNotFoundError, PermissionError, OSError) as exc:
            return CommandResult(returncode=127, output=str(exc))
        return CommandResult(proc.returncode, proc.stdout.decode(errors="replace"))


def _groups_of(run_as: RunAs) -> list[int]:
    try:
        return os.getgrouplist(run_as.user, run_as.gid)
    except (KeyError, OSError):
        return [run_as.gid]
