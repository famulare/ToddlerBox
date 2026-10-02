from toddlerbox.runtime import health


def test_shutdown_ack_is_not_suppressed_by_frame_throttle(monkeypatch):
    messages = []
    class Client:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
        def setblocking(self, _value):
            pass
        def sendto(self, message, address):
            messages.append((message, address))
    monkeypatch.setenv("TODDLERBOX_HEALTH_SOCKET", "/run/test-health.sock")
    monkeypatch.setattr(health.socket, "socket", lambda *_args: Client())
    monkeypatch.setattr(health.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(health, "_last_frame", 0.0)
    health.frame_complete()
    health.frame_complete()
    health.shutdown_complete()
    assert messages == [(b"frame", "/run/test-health.sock"),
                        (b"shutdown-complete", "/run/test-health.sock")]


def test_unavailable_health_socket_does_not_interrupt_cleanup(monkeypatch):
    monkeypatch.setenv("TODDLERBOX_HEALTH_SOCKET", "/run/missing-health.sock")
    def unavailable(*_args):
        raise OSError("socket unavailable")
    monkeypatch.setattr(health.socket, "socket", unavailable)
    health.shutdown_complete()
