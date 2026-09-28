"""Native daemon refresh preserves config and fails closed on transport errors."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest import TestCase


def _installer():
    spec = importlib.util.spec_from_file_location(
        "harness_reload_install", Path(__file__).resolve().parents[1] / "install.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _read_exact(conn, size):
    result = b""
    while len(result) < size:
        chunk = conn.recv(size - len(result))
        if not chunk:
            raise EOFError("client closed connection")
        result += chunk
    return result


def _read_frame(conn):
    first, second = _read_exact(conn, 2)
    assert first & 0x80, "client must send complete frames"
    assert second & 0x80, "WebSocket client frames must be masked"
    length = second & 127
    if length == 126:
        length = struct.unpack("!H", _read_exact(conn, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _read_exact(conn, 8))[0]
    mask = _read_exact(conn, 4)
    data = _read_exact(conn, length)
    return first & 15, bytes(c ^ mask[i % 4] for i, c in enumerate(data))


def _send_frame(conn, payload, opcode=1):
    if isinstance(payload, dict):
        payload = json.dumps(payload).encode()
    length = len(payload)
    header = bytes([0x80 | opcode])
    header += bytes([length]) if length < 126 else b"\x7e" + struct.pack("!H", length)
    conn.sendall(header + payload)


@contextmanager
def _daemon(tmp_path, mode="success"):
    path = tmp_path / "native.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen(1)
    listener.settimeout(3)
    requests, errors = [], []
    done = threading.Event()

    def serve():
        try:
            with listener.accept()[0] as conn:
                conn.settimeout(3)
                header = b""
                while not header.endswith(b"\r\n\r\n"):
                    header += _read_exact(conn, 1)
                    assert len(header) < 16384
                fields = dict(line.split(":", 1) for line in header.decode().split("\r\n")[1:] if ":" in line)
                fields = {key.lower(): value.strip() for key, value in fields.items()}
                key = fields["sec-websocket-key"]
                accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
                if mode == "bad_accept":
                    accept = "not-the-request-key"
                conn.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + accept + "\r\n\r\n").encode())
                if mode == "bad_accept":
                    return
                opcode, payload = _read_frame(conn)
                assert opcode == 1
                requests.append(json.loads(payload))
                if mode == "timeout":
                    done.wait(1)
                    return
                if mode == "close":
                    _send_frame(conn, b"", opcode=8)
                    return
                if mode == "malformed":
                    _send_frame(conn, b"{broken")
                    return
                if mode == "oversized":
                    conn.sendall(b"\x81\x7f" + struct.pack("!Q", 2**40))
                    return
                if mode in {"masked", "fragmented"}:
                    conn.sendall(b"\x81\x80" if mode == "masked" else b"\x01\x00")
                    return
                if mode == "nonobject":
                    _send_frame(conn, b"[]")
                    return
                if mode == "missingresult":
                    _send_frame(conn, {"id": 1})
                    return
                if mode == "exhausted":
                    for _ in range(64):
                        _send_frame(conn, {"id": 99, "result": {}})
                    return
                if mode == "notification":
                    _send_frame(conn, {"method": "server/notice", "params": {}})
                if mode == "ping":
                    _send_frame(conn, b"keepalive", opcode=9)
                    assert _read_frame(conn) == (10, b"keepalive")
                _send_frame(conn, {"id": 1, "result": {"userAgent": "fake-native"}})
                for _ in range(2):
                    opcode, payload = _read_frame(conn)
                    assert opcode == 1
                    requests.append(json.loads(payload))
                reply = {"id": 2, "result": {"status": "ok"}}
                if mode == "failed_status":
                    reply = {"id": 2, "result": {"status": "failed"}}
                if mode == "rpc_error":
                    reply = {"id": 2, "error": {"code": -32603, "message": "refresh refused"}}
                _send_frame(conn, reply)
        except BaseException as exc:
            errors.append(exc)
        finally:
            listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield str(path), requests
    finally:
        done.set()
        thread.join(4)
        assert not thread.is_alive(), "fake daemon failed to terminate"
        assert not errors, errors


def pytest_generate_tests(metafunc):
    if "failure_mode" in metafunc.fixturenames:
        metafunc.parametrize("failure_mode", ["bad_accept", "rpc_error", "timeout", "close", "malformed", "oversized", "failed_status", "masked", "fragmented", "nonobject", "missingresult", "exhausted"])
    if "success_mode" in metafunc.fixturenames:
        metafunc.parametrize("success_mode", ["success", "ping", "notification"])


def test_native_reload_sends_only_empty_config_refresh(tmp_path, success_mode):
    module = _installer()
    config = tmp_path / "config.toml"
    original = b'[features]\nhooks = true\n# preserve unrelated settings\n'
    config.write_bytes(original)
    with _daemon(tmp_path, success_mode) as (path, requests):
        module._reload_codex_daemon_hooks(path, timeout=1)
    assert len(requests) == 3
    assert requests[0]["id"] == 1
    assert requests[0]["method"] == "initialize"
    assert requests[1]["method"] == "initialized"
    assert "id" not in requests[1]
    assert requests[2] == {"id": 2, "method": "config/batchWrite", "params": {"edits": [], "reloadUserConfig": True}}
    assert config.read_bytes() == original


def test_native_reload_rejects_transport_and_rpc_failures(tmp_path, failure_mode):
    module = _installer()
    with _daemon(tmp_path, failure_mode) as (path, _):
        if failure_mode == "exhausted":
            with TestCase().assertRaisesRegex(ValueError, "message limit"):
                module._reload_codex_daemon_hooks(path, timeout=1)
        else:
            with TestCase().assertRaises((OSError, ValueError, TimeoutError)):
                module._reload_codex_daemon_hooks(path, timeout=0.15)


def test_native_reload_rejects_non_socket_without_writing(tmp_path):
    module = _installer()
    path = tmp_path / "not-a-socket"
    path.write_bytes(b"do not change")
    with TestCase().assertRaises((OSError, ValueError)):
        module._reload_codex_daemon_hooks(str(path), timeout=0.1)
    assert path.read_bytes() == b"do not change"


def test_custom_config_never_refreshes_unrelated_native_daemon(tmp_path, monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    module = _installer()
    def forbidden(*args, **kwargs):
        raise AssertionError("custom config must not discover or refresh the user's daemon")
    monkeypatch.setattr(module, "_run", forbidden)
    monkeypatch.setattr(module, "_reload_codex_daemon_hooks", forbidden)
    ok, detail = module._reload_codex_runtime(str(tmp_path / "other.toml"))
    assert ok, detail
    assert detail


def test_discovery_refreshes_only_reported_native_socket(tmp_path, monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    module = _installer()
    calls = []
    with _daemon(tmp_path) as (path, requests):
        def discover(command, dry):
            calls.append((command, dry))
            return 0, json.dumps({"status": "running", "socketPath": path}), ""
        monkeypatch.setattr(module, "_run", discover)
        ok, detail = module._reload_codex_runtime(None)
    assert ok, detail
    assert calls == [(["codex", "app-server", "daemon", "version"], False)]
    assert requests[-1]["params"] == {"edits": [], "reloadUserConfig": True}


def test_discovery_rejects_unknown_or_malformed_native_status(monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    module = _installer()
    def unexpected(*args, **kwargs):
        raise AssertionError("invalid discovery must not reach a socket")
    monkeypatch.setattr(module, "_reload_codex_daemon_hooks", unexpected)
    for result in [(0, "not json", ""),
                   (0, "[]", ""), (0, '{"status":"unknown"}', ""),
                   (0, '{"status":"running","socketPath":4}', "")]:
        monkeypatch.setattr(module, "_run", lambda *args, value=result: value)
        ok, detail = module._reload_codex_runtime(None)
        assert not ok, result
        assert detail


def test_discovery_reports_native_reload_failure(monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    module = _installer()
    monkeypatch.setattr(module, "_run", lambda *args: (0, '{"status":"running","socketPath":"/unused"}', ""))
    def fail(*args, **kwargs):
        raise TimeoutError("test deadline")
    monkeypatch.setattr(module, "_reload_codex_daemon_hooks", fail)
    ok, detail = module._reload_codex_runtime(None)
    assert not ok
    assert "test deadline" in detail


def test_native_reload_rejects_endpoint_parent_owned_by_another_user(tmp_path, monkeypatch):
    module = _installer()
    path = tmp_path / "foreign.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as endpoint:
        endpoint.bind(str(path))
        monkeypatch.setattr(module.os, "getuid", lambda: os.stat(path).st_uid + 1)
        with TestCase().assertRaises((OSError, ValueError)):
            module._reload_codex_daemon_hooks(str(path), timeout=0.1)


def test_native_reload_supports_native_control_socket_symlink(tmp_path):
    module = _installer()
    with _daemon(tmp_path) as (path, requests):
        link = tmp_path / "control.sock"
        link.symlink_to(path)
        module._reload_codex_daemon_hooks(str(link), timeout=1)
    assert requests[-1]["method"] == "config/batchWrite"


def test_no_daemon_endpoint_defers_hooks_to_next_session(tmp_path, monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    module = _installer()
    monkeypatch.setattr(module, "DEFAULT_CODEX_CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(module, "_run", lambda *args: (1, "", "not running"))
    ok, detail = module._reload_codex_runtime(None)
    assert ok, detail
    assert "next session" in detail


def test_discovery_error_with_existing_endpoint_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    module = _installer()
    monkeypatch.setattr(module, "DEFAULT_CODEX_CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(module, "_run", lambda *args: (1, "", "permission denied"))
    endpoint = tmp_path / "app-server-control" / "app-server-control.sock"
    endpoint.parent.mkdir()
    # A dangling native control symlink is still an endpoint needing repair.
    endpoint.symlink_to(tmp_path / "missing.sock")
    ok, detail = module._reload_codex_runtime(None)
    assert not ok
    assert "not refreshed" in detail


def test_native_reload_rejects_writable_endpoint_parent(tmp_path):
    module = _installer()
    directory = tmp_path / "shared"
    directory.mkdir(mode=0o777)
    directory.chmod(0o777)
    path = directory / "socket"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as endpoint:
        endpoint.bind(str(path))
        with TestCase().assertRaisesRegex(ValueError, "directory"):
            module._reload_codex_daemon_hooks(str(path), timeout=0.1)


def test_native_reload_rejects_unsafe_symlink_target_parent(tmp_path):
    module = _installer()
    directory = tmp_path / "shared"
    directory.mkdir()
    directory.chmod(0o777)
    path = directory / "socket"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as endpoint:
        endpoint.bind(str(path))
        link = tmp_path / "safe-looking.sock"
        link.symlink_to(path)
        with TestCase().assertRaisesRegex(ValueError, "directory"):
            module._reload_codex_daemon_hooks(str(link), timeout=0.1)


def test_native_reload_checks_socket_owner_after_private_parent(tmp_path, monkeypatch):
    module = _installer()
    path = tmp_path / "foreign.sock"
    real_stat = Path.stat
    def stat_with_foreign_socket(self, *args, **kwargs):
        info = real_stat(self, *args, **kwargs)
        if self == path:
            return SimpleNamespace(st_uid=os.getuid() + 1, st_mode=info.st_mode)
        return info
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as endpoint:
        endpoint.bind(str(path))
        monkeypatch.setattr(Path, "stat", stat_with_foreign_socket)
        with TestCase().assertRaisesRegex(ValueError, "user-owned Unix socket"):
            module._reload_codex_daemon_hooks(str(path), timeout=0.1)


def test_native_reload_checks_connected_peer_owner(tmp_path, monkeypatch):
    module = _installer()
    path = tmp_path / "peer.sock"
    real_socket = socket.socket
    class ForeignPeerSocket(real_socket):
        def getsockopt(self, level, option, *args):
            if level == socket.SOL_SOCKET and option == socket.SO_PEERCRED:
                return struct.pack("3i", os.getpid(), os.getuid() + 1, os.getgid())
            return super().getsockopt(level, option, *args)
    with real_socket(socket.AF_UNIX, socket.SOCK_STREAM) as endpoint:
        endpoint.bind(str(path))
        endpoint.listen(1)
        monkeypatch.setattr(module.socket, "socket", ForeignPeerSocket)
        with TestCase().assertRaisesRegex(ValueError, "peer has a different owner"):
            module._reload_codex_daemon_hooks(str(path), timeout=0.1)


def test_explicit_config_matching_codex_home_refreshes_that_daemon(tmp_path, monkeypatch):
    module = _installer()
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    calls = []
    monkeypatch.setattr(module, "_run", lambda *args: (0, '{"status":"running","socketPath":"/test-only"}', ""))
    monkeypatch.setattr(module, "_reload_codex_daemon_hooks", lambda path: calls.append(path))
    ok, detail = module._reload_codex_runtime(str(tmp_path / "config.toml"))
    assert ok, detail
    assert calls == ["/test-only"]


def test_default_config_mismatching_codex_home_skips_daemon(tmp_path, monkeypatch):
    module = _installer()
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    def forbidden(*args, **kwargs):
        raise AssertionError("different runtime home must not be probed")
    monkeypatch.setattr(module, "_run", forbidden)
    ok, detail = module._reload_codex_runtime(None)
    assert ok, detail
    assert "new session" in detail


def test_daemon_discovery_timeout_returns_failure(monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    module = _installer()
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(["codex"], 1)
    monkeypatch.setattr(module, "_run", timeout)
    ok, detail = module._reload_codex_runtime(None)
    assert not ok
    assert "not refreshed" in detail
