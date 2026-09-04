"""Tests for the TTL board reservation primitive (no real labgrid)."""

import pytest

from mcp_server.orchestration import reservation


class FakePlace:
    def __init__(self, name, tags, acquired=None, config=True):
        self.name = name
        self.tags = tags
        self.acquired = acquired
        self._config = config

    def get_config(self):
        return self._config


class FakeSession:
    def __init__(self, places):
        self.places = {p.name: p for p in places}
        self.acquired = []
        self.released = []
        self.stopped = False
        self.closed = False

    def gethostname(self):
        return "host"

    def getuser(self):
        return "user"

    def acquire(self):
        self.acquired.append(True)

    def release(self):
        self.released.append(True)

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def _factory(session):
    return lambda: session


def test_reserve_picks_matching_place_and_acquires():
    reservation._RESERVATIONS.clear()
    session = FakeSession([
        FakePlace("sc598-a", {"sc598": True, "ezkit": True}),
        FakePlace("other", {"sc589": True}),
    ])
    clock = Clock()
    res = reservation.reserve(["sc598"], session_factory=_factory(session),
                              clock=clock, ttl_seconds=100)
    assert res.place == "sc598-a"
    assert session.acquired == [True]
    assert res.expires_at == 1100.0


def test_reserve_skips_place_without_config():
    reservation._RESERVATIONS.clear()
    session = FakeSession([FakePlace("sc598-a", {"sc598": True}, config=False)])
    with pytest.raises(RuntimeError, match="no place"):
        reservation.reserve(["sc598"], session_factory=_factory(session),
                            clock=Clock())


def test_reserve_skips_place_acquired_by_other():
    reservation._RESERVATIONS.clear()
    session = FakeSession([
        FakePlace("sc598-a", {"sc598": True}, acquired="host/someone-else"),
    ])
    with pytest.raises(RuntimeError, match="no available"):
        reservation.reserve(["sc598"], session_factory=_factory(session),
                            clock=Clock())


def test_reserve_tears_down_session_when_no_match():
    # A started session leaks its grpc pump task onto labgrid's stashed event
    # loop; leaving it open poisons the loop for the whole process, so every
    # later reserve in a long-lived server fails with "Could not connect".
    # When matching fails, the session must be stopped and closed.
    reservation._RESERVATIONS.clear()
    session = FakeSession([FakePlace("sc598-a", {"sc598": True}, config=False)])
    with pytest.raises(RuntimeError, match="no place"):
        reservation.reserve(["sc598"], session_factory=_factory(session),
                            clock=Clock())
    assert session.stopped is True
    assert session.closed is True


def test_get_raises_when_expired():
    reservation._RESERVATIONS.clear()
    session = FakeSession([FakePlace("sc598-a", {"sc598": True})])
    clock = Clock(1000.0)
    res = reservation.reserve(["sc598"], session_factory=_factory(session),
                              clock=clock, ttl_seconds=10)
    clock.t = 1011.0
    with pytest.raises(KeyError):
        reservation.get(res.token, clock=clock)


def test_release_releases_session():
    reservation._RESERVATIONS.clear()
    session = FakeSession([FakePlace("sc598-a", {"sc598": True})])
    res = reservation.reserve(["sc598"], session_factory=_factory(session),
                              clock=Clock())
    reservation.release(res.token)
    assert session.released == [True]
    with pytest.raises(KeyError):
        reservation.get(res.token, clock=Clock())


# --- async-labgrid driving (real ClientSession.acquire/release are coroutines
#     that must run on session.loop and read self.args.place) ----------------

class FakeLoop:
    """Records run_until_complete and steps a no-await coroutine to completion."""

    def __init__(self):
        self.count = 0

    def run_until_complete(self, coro):
        self.count += 1
        try:
            coro.send(None)
        except StopIteration as exc:
            return exc.value


class AsyncFakeSession:
    def __init__(self, places):
        self.places = {p.name: p for p in places}
        self.acquired = []
        self.released = []
        self.stopped = False
        self.closed = False
        self.args = None
        self.loop = FakeLoop()

    def gethostname(self):
        return "host"

    def getuser(self):
        return "user"

    async def acquire(self):
        # Mirror labgrid: the place to acquire comes from self.args.place.
        self.acquired.append(self.args.place)

    async def release(self):
        self.released.append(True)

    async def stop(self):
        self.stopped = True

    async def close(self):
        self.closed = True


def test_reserve_drives_async_acquire_and_binds_place():
    reservation._RESERVATIONS.clear()
    session = AsyncFakeSession([
        FakePlace("sc598-a", {"sc598": True, "ezkit": True}),
    ])
    res = reservation.reserve(["sc598"], session_factory=lambda: session,
                              clock=Clock())
    assert res.place == "sc598-a"
    # Place bound onto session.args so async acquire() can read it.
    assert session.args.place == "sc598-a"
    # acquire() ran on the event loop and observed the bound place.
    assert session.acquired == ["sc598-a"]
    assert session.loop.count >= 1


def test_release_drives_async_release_stop_close():
    reservation._RESERVATIONS.clear()
    session = AsyncFakeSession([FakePlace("sc598-a", {"sc598": True})])
    res = reservation.reserve(["sc598"], session_factory=lambda: session,
                              clock=Clock())
    reservation.release(res.token)
    assert session.released == [True]
    assert session.stopped is True
    assert session.closed is True


def test_matching_places_returns_names_and_tears_down():
    # tag_resolver in the long-lived MCP server must NOT leak its discovery
    # session: a leaked grpc pump task poisons labgrid's stashed loop and the
    # next reserve fails with "Could not connect to coordinator". So scanning
    # for matching places must stop+close the session even on success.
    session = FakeSession([
        FakePlace("sc598-a", {"sc598": True, "ezkit": True}),
        FakePlace("sc846-a", {"sc846": True}),
        FakePlace("sc598-b", {"sc598": True, "ezkit": True}, config=False),
    ])
    names = reservation.matching_places(
        ["sc598", "ezkit"], session_factory=lambda: session)
    assert names == ["sc598-a"]  # sc846 wrong tags, sc598-b no config
    assert session.stopped is True
    assert session.closed is True


def test_matching_places_tears_down_on_scan_error():
    class Boom(FakeSession):
        @property
        def places(self):
            raise RuntimeError("scan blew up")

        @places.setter
        def places(self, v):
            self._places = v

    session = Boom([FakePlace("sc598-a", {"sc598": True})])
    with pytest.raises(RuntimeError, match="scan blew up"):
        reservation.matching_places(["sc598"], session_factory=lambda: session)
    assert session.stopped is True
    assert session.closed is True
