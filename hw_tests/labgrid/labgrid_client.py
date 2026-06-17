import os
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True)
class LabgridClient:
    coordinator: str | None = None
    config: str | None = None
    timeout: int = 30

    def command(self, *args, place=None):
        command = ["labgrid-client"]
        if self.coordinator:
            command.extend(["-x", self.coordinator])
        if self.config:
            command.extend(["-c", self.config])
        if place:
            command.extend(["-p", place])
        command.extend(args)
        return command

    def run(self, *args, place=None, check=True, timeout=None):
        return subprocess.run(
            self.command(*args, place=place),
            check=check,
            capture_output=True,
            text=True,
            timeout=self.timeout if timeout is None else timeout,
        )


def split_places(value):
    return (value or "").replace(",", " ").split()


def places_from_env():
    return split_places(os.environ.get("LG_TARGETS") or os.environ.get("LG_PLACE"))


def list_places(client):
    result = client.run("places")
    return [line for line in result.stdout.splitlines() if line.strip()]


def acquire_place(client, place):
    result = client.run("acquire", place=place, check=False)
    if result.returncode == 0:
        return True

    output = f"{result.stdout}\n{result.stderr}"
    if f"You have already acquired place {place}." in output:
        return False

    result.check_returncode()


def release_place(client, place):
    return client.run("release", place=place, check=False)


@contextmanager
def acquired_places(client, places, acquire=True):
    acquired = []
    try:
        if acquire:
            for place in places:
                if acquire_place(client, place):
                    acquired.append(place)
        yield
    finally:
        for place in reversed(acquired):
            release_place(client, place)
