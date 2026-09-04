"""TTL board reservation spanning separate MCP tool calls.

labgrid does not release a place when a client disconnects, so a reservation
held across separate calls needs its own TTL cleanup, done here. Place matching
uses ``place.get_config()`` (current coordinator model) — never envs/*.yaml.

The session factory and clock are injected so this module is unit-testable with
no real labgrid and no wall-clock sleeps.
"""

from __future__ import annotations

import inspect
import secrets
from argparse import Namespace
from dataclasses import dataclass


@dataclass
class Reservation:
    token: str
    place: str
    session: object
    expires_at: float


_RESERVATIONS: dict[str, Reservation] = {}


def _place_tags(place) -> set:
    tags = set(place.tags)
    tags.update(str(value) for value in place.tags.values())
    return tags


def _drive(session, method_name, *args):
    """Call ``session.<method_name>`` and, if it returns a coroutine, run it on
    the session's event loop.

    Real labgrid ``ClientSession.acquire/release/stop/close`` are coroutines
    that must run on ``session.loop``; the sync test fakes return None. This
    keeps one code path for both.
    """
    method = getattr(session, method_name, None)
    if method is None:
        return None
    result = method(*args)
    if inspect.iscoroutine(result):
        return session.loop.run_until_complete(result)
    return result


def _bind_place(session, place):
    """Bind the chosen place onto ``session.args`` so ``acquire()`` finds it.

    Real labgrid ``acquire()`` reads ``self.args.place`` (and
    ``self.args.allow_unmatched``). A discovery session built by a bare
    ``start_session`` has ``args=None``; give it the same Namespace shape the
    proven ``labgrid.py`` acquire path uses.
    """
    session.args = Namespace(
        allow_unmatched=False,
        initial_state=None,
        kick=True,
        place=place,
        state=None,
    )


def _find_candidate(session, needs, requested):
    owner = f"{session.gethostname()}/{session.getuser()}"
    matches = []
    candidates = []
    for place in session.places.values():
        if requested and place.name != requested:
            continue
        tags = _place_tags(place)
        if not (all(need in tags for need in needs) and place.get_config()):
            continue
        matches.append(place)
        if place.acquired in (None, owner):
            candidates.append(place)
    if not matches:
        raise RuntimeError(f"no place found for needs: {needs}")
    if not candidates:
        held = ", ".join(f"{p.name} by {p.acquired}" for p in matches)
        raise RuntimeError(f"no available place for needs: {needs} ({held})")
    return min(candidates, key=lambda p: p.name).name


def reserve(needs, *, requested=None, ttl_seconds=1800, session_factory, clock):
    session = session_factory()
    # start_session() has already started a grpc pump task on labgrid's
    # stashed (ContextVar) event loop. If anything below raises, that task and
    # channel leak on the shared loop and poison every later reserve in a
    # long-lived process ("Could not connect to coordinator"). Tear the session
    # down on any failure — releasing only if we got as far as acquiring.
    acquired = False
    try:
        place = _find_candidate(session, needs, requested)
        _bind_place(session, place)
        _drive(session, "acquire")
        acquired = True
        token = secrets.token_hex(16)
        _RESERVATIONS[token] = Reservation(
            token=token, place=place, session=session,
            expires_at=clock() + ttl_seconds,
        )
        return _RESERVATIONS[token]
    except Exception:
        _teardown(session, release=acquired)
        raise


def matching_places(needs, *, session_factory) -> list[str]:
    """Return names of live places matching ``needs``, tearing the session down.

    A read-only discovery scan for callers that need place names without
    holding a reservation (e.g. the test-writer tag check). Like ``reserve``,
    it must always stop+close the session: a leaked grpc pump task poisons
    labgrid's stashed event loop and every later ``reserve`` in a long-lived
    process then fails with "Could not connect to coordinator".
    """
    session = session_factory()
    try:
        names = []
        for place in session.places.values():
            tags = _place_tags(place)
            if all(need in tags for need in needs) and place.get_config():
                names.append(place.name)
        return sorted(names)
    finally:
        _teardown(session, release=False)


def get(token, *, clock):
    entry = _RESERVATIONS[token]
    if clock() >= entry.expires_at:
        del _RESERVATIONS[token]
        raise KeyError(token)
    return entry


def _teardown(session, *, release):
    """Tear a session down: optionally release the place, then always stop the
    pump task and close the channel so nothing leaks on the shared event loop.
    """
    try:
        if release:
            _drive(session, "release")
    finally:
        try:
            _drive(session, "stop")
        finally:
            _drive(session, "close")


def _release_entry(entry):
    _teardown(entry.session, release=True)


def release(token):
    entry = _RESERVATIONS.pop(token)
    _release_entry(entry)
