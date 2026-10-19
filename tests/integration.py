"""Independent bridge process fixtures; no Steam, publisher binary, or game runs."""
import argparse
import contextlib
import ctypes
import http.client
import http.server
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import threading
import time
import unittest


def unused_port(address="127.0.0.2"):
    with socket.socket() as listener:
        listener.bind((address, 0))
        return listener.getsockname()[1]


def wait_json(path, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            return json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(0.025)
    raise AssertionError(f"Fixture marker was not produced: {path.name}")


def alive(pid):
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_uint32()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        status = Path(f"/proc/{pid}/status")
        if status.exists() and "\nState:\tZ" in status.read_text():
            return False
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def stop_fixture(pid):
    if not alive(pid):
        return
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(1, False, pid)
        if handle:
            kernel.TerminateProcess(handle, 90)
            kernel.CloseHandle(handle)
    else:
        os.kill(pid, signal.SIGKILL)


class EchoPublisher(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        response = json.dumps({
            "path": self.path,
            "host": self.headers.get("Host"),
            "scheme": self.headers.get("X-SacredFire-Scheme"),
            "header": self.headers.get("X-Fixture-Header"),
            "hop_header_absent": self.headers.get("X-Fixture-Hop") is None,
            "body_bytes": list(body),
        }).encode()
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Publisher-Fixture", "preserved")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Connection", "close")
        self.end_headers()
        # Deliberately split a binary-safe JSON reply to exercise proxy dechunking.
        for chunk in [response[:13], response[13:]]:
            self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
        self.wfile.write(b"0\r\n\r\n")
        self.close_connection = True


class BodylessPublisher(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, status, length=None):
        self.server.requests.append((self.command, self.path))
        self.send_response(status)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def do_HEAD(self):
        self.reply(200, 12345678 if self.path == "/large-representation" else 123)

    def do_GET(self):
        if self.path == "/no-content":
            self.reply(204)
        elif self.path == "/not-modified-no-length":
            self.reply(304)
        elif self.path == "/large-not-modified":
            self.reply(304, 12345678)
        else:
            self.reply(304, 123)

    def do_POST(self):
        self.reply(200, 0)


class BridgeIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bridge fixtures ", dir=ARGS.work_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for folder in ["game", "prepared", "patches", "profile", "lab"]:
            (self.root / folder).mkdir()
        for file in ["game/eboot.bin", "prepared/boot-linked.bin", "prepared/import_names.txt",
                     "prepared/content.bin", "prepared/patches.bin", "fixture-signing-key"]:
            (self.root / file).write_bytes(b"inert fixture file, never executed\n")
        self.http_port = unused_port()
        self.auth_port = unused_port()
        while self.auth_port == self.http_port:
            self.auth_port = unused_port()
        self.env = os.environ.copy()
        for key in list(self.env):
            if key.startswith("TEST_"):
                del self.env[key]
        self.env.update(TEST_CASE_ROOT=str(self.root), TEST_PROVIDER_LOG=str(self.root / "provider.jsonl"),
                        BB_OSW_STALE_FIXTURE="must-not-reach-host", CTR_STALE_FIXTURE="must-not-reach-host")

    def config(self, *, provider=None, lab=True, name="Fixture !+", unlock=False):
        # steam.library names the bridge binary as inert fixture input; the fake
        # provider never loads it. No real user-supplied Steam library is touched.
        return f"""[platform]
provider = steam
library = {json.dumps(str(provider or ARGS.provider))}
[steam]
app_id = 876543
library = {json.dumps(ARGS.bridge.name)}
[player]
online_id = {json.dumps(name)}
unlock_all = {str(unlock).lower()}
[game]
host = native
executable = {json.dumps(str(ARGS.host))}
game_dir = {json.dumps(str(self.root / 'game'))}
prepared_dir = {json.dumps(str(self.root / 'prepared'))}
patches_dir = {json.dumps(str(self.root / 'patches'))}
profile_dir = {json.dumps(str(self.root / 'profile'))}
[publisher]
executable = {json.dumps(str(ARGS.host))}
signing_key = {json.dumps(str(self.root / 'fixture-signing-key'))}
weak_admission = true
[session]
title = FIXTURE
build = fixture-build
realm = fixture-realm
[network]
server = 127.0.0.2
game_address = 127.0.0.1
http_port = {self.http_port}
auth_port = {self.auth_port}
""" + (f"""[lab]
enabled = true
account_id = 123456789
root = {json.dumps(str(self.root / 'lab'))}
""" if lab else "")

    def invoke(self, config=None, arguments=(), *, mode="early", timeout=15):
        path = self.root / "fixture.ini"
        path.write_text(config or self.config(), encoding="utf-8")
        environment = dict(self.env, TEST_HOST_MODE=mode)
        return subprocess.run([str(ARGS.bridge), "--config", str(path), *arguments],
                              env=environment, capture_output=True, text=True,
                              timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

    def events(self):
        return [json.loads(line) for line in (self.root / "provider.jsonl").read_text().splitlines()]

    def assert_clean_shutdown(self):
        self.assertEqual([entry["event"] for entry in self.events()][-2:], ["stop", "destroy"])

    @contextlib.contextmanager
    def running_bridge(self):
        config = self.root / "fixture.ini"
        config.write_text(self.config(), encoding="utf-8")
        process = subprocess.Popen([str(ARGS.bridge), "--config", str(config)],
                                   env=dict(self.env, TEST_HOST_MODE="hold"),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        pids = []
        try:
            host = wait_json(self.root / "host.json")
            child = wait_json(self.root / "descendant.json")
            pids = [host["pid"], child["pid"]]
            self.assertIsNone(process.poll(), "Bridge exited before HTTP fixture")
            yield process
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)
            for pid in pids:
                stop_fixture(pid)

    @contextlib.contextmanager
    def publisher(self, handler):
        server = http.server.ThreadingHTTPServer(("127.0.0.2", self.auth_port), handler)
        server.requests = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)

    def test_check_and_invalid_configuration_never_launch(self):
        good = self.invoke(arguments=("--check",))
        self.assertEqual(good.returncode, 0, good.stderr)
        for before, after in [
            ("provider = steam", "provider = unsupported"),
            ("unlock_all = false", "unlock_all = 1"),
            ("app_id = 876543", "app_id = 0"),
            ("game_address = 127.0.0.1", "game_address = 0.0.0.0"),
            ("weak_admission = true", "weak_admission = false"),
            ("[player]", "[unknown]"),
            ("[player]", "[player]\nunknown_key = value"),
        ]:
            with self.subTest(setting=before):
                failed = self.invoke(self.config().replace(before, after), arguments=("--check",))
                self.assertNotEqual(failed.returncode, 0)
                self.assertIn("ctrnf-p2p:", failed.stderr)
        self.assertFalse((self.root / "host.json").exists())
        self.assertFalse((self.root / "provider.jsonl").exists())

    def test_missing_provider_and_required_symbol_fail_before_host(self):
        absent = self.invoke(self.config(provider=self.root / "does-not-exist.dll"))
        self.assertNotEqual(absent.returncode, 0)
        self.assertIn("platform.library", absent.stderr)
        incomplete = self.invoke(self.config(provider=ARGS.missing_provider))
        self.assertNotEqual(incomplete.returncode, 0)
        self.assertIn("osw_get_persona_name", incomplete.stderr)
        self.assertFalse((self.root / "host.json").exists())
        self.assertFalse((self.root / "provider.jsonl").exists())

    def test_probe_and_persona_bootstrap_do_not_launch_host(self):
        result = self.invoke(self.config(lab=False, name=""), arguments=("--probe",))
        self.assertEqual(result.returncode, 0, result.stderr)
        creates = [e for e in self.events() if e["event"] == "create"]
        self.assertEqual(len(creates), 2)
        self.assertFalse(creates[0]["companion"])
        self.assertEqual(creates[1]["online_id"], "Fixture _!")
        self.assertTrue(creates[1]["companion"])
        self.assertEqual([e["value"] for e in self.events() if e["event"] == "appid"], [876543, 876543])
        self.assertEqual(len([e for e in self.events() if e["event"] == "defer_endpoint"]), 1)
        self.assertFalse(any(e["event"] == "bind_endpoint" for e in self.events()))
        self.assertFalse((self.root / "host.json").exists())
        self.assert_clean_shutdown()

    def test_directory_check_discovers_and_leaves_room_without_host(self):
        result = self.invoke(arguments=("--directory-check",))
        self.assertEqual(result.returncode, 0, result.stderr)
        operations = [event for event in self.events() if event["event"] == "directory"]
        self.assertEqual(operations[0]["op"], "directory.create")
        self.assertIn("directory.members", [event["op"] for event in operations])
        self.assertIn("directory.search", [event["op"] for event in operations])
        self.assertEqual(operations[-1]["op"], "directory.leave")
        events = self.events()
        self.assertLess(next(i for i, e in enumerate(events) if e["event"] == "bind_endpoint"),
                        next(i for i, e in enumerate(events) if e["event"] == "directory"))
        self.assertTrue(all(event["status"] == 0 for event in operations))
        self.assertFalse(self.events()[-2]["room_active"])
        self.assertFalse((self.root / "host.json").exists())
        self.assertIn("no game or peer transport acceptance implied", result.stdout)
        self.assert_clean_shutdown()

    def test_directory_check_read_or_search_failure_still_leaves_room(self):
        offset = 0
        for failure in ["read", "search"]:
            with self.subTest(failure=failure):
                self.env["TEST_DIRECTORY_FAILURE"] = failure
                result = self.invoke(arguments=("--directory-check",), timeout=30)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("Directory check", result.stderr)
                events = self.events()[offset:]
                offset += len(events)
                operations = [event for event in events if event["event"] == "directory"]
                failed_operation = "directory.members" if failure == "read" else "directory.search"
                self.assertTrue(any(event["op"] == failed_operation and event["status"] != 0 for event in operations))
                self.assertEqual(operations[-1], {"event": "directory", "op": "directory.leave", "status": 0})
                self.assertFalse(events[-2]["room_active"], "Diagnostic left a live room after failure")
                self.assertFalse((self.root / "host.json").exists())
                self.assert_clean_shutdown()

    def test_early_exit_maps_failure_and_preserves_host_contract(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 3, result.stderr)
        report = wait_json(self.root / "host.json")
        self.assertEqual(report["arguments"][-2:], ["--timeout", "0"])
        self.assertEqual(report["saves"], report["gpu_user"])
        self.assertEqual(report["online_id"], report["user_name"])
        self.assertEqual(report["online_id"], "Fixture !+")
        self.assertEqual(report["game_profile"], "ctr")
        self.assertTrue(report["private_inheritance_removed"])
        self.assertTrue(report["account_matches_fixture"])
        self.assertFalse(alive(report["pid"]))
        self.assert_clean_shutdown()

    def test_owned_udp_endpoint_waits_for_socket_then_registers_exact_port(self):
        result = self.invoke(mode="delayed")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = wait_json(self.root / "host.json")
        self.assertTrue(report["endpoint_ready"])
        binds = [e for e in self.events() if e["event"] == "bind_endpoint"]
        self.assertEqual(binds, [{"event": "bind_endpoint", "address": "127.0.0.1", "port": report["udp_port"], "status": 0}])
        self.assert_clean_shutdown()

    def test_ambiguous_or_wrong_address_udp_endpoint_fails_closed(self):
        for mode in ["ambiguous", "wrong-address"]:
            with self.subTest(mode=mode):
                result = self.invoke(mode=mode)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("UDP", result.stderr)
                self.assertFalse(alive(wait_json(self.root / "host.json")["pid"]))
                self.assert_clean_shutdown()

    def test_rejected_endpoint_registration_stops_owned_host(self):
        self.env["TEST_ENDPOINT_REJECT"] = "1"
        result = self.invoke(mode="hold")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("endpoint registration", result.stderr)
        self.assertFalse(alive(wait_json(self.root / "host.json")["pid"]))
        self.assert_clean_shutdown()

    def test_closed_or_changed_owned_udp_endpoint_stops_session(self):
        for mode in ["closed", "changed"]:
            with self.subTest(mode=mode):
                result = self.invoke(mode=mode)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("UDP endpoint closed or changed", result.stderr)
                report = wait_json(self.root / "host.json")
                self.assertTrue(report["endpoint_ready"])
                self.assertFalse(alive(report["pid"]))
                self.assert_clean_shutdown()

    def test_economy_changes_only_local_state(self):
        snapshots = []
        for unlocked in [False, True]:
            result = self.invoke(self.config(unlock=unlocked), arguments=("--probe",))
            self.assertEqual(result.returncode, 0, result.stderr)
            snapshots.append([e for e in self.events() if e["event"] == "create"][-1])
        normal, unlocked = snapshots
        for field in ["title", "build", "realm"]:
            self.assertEqual(normal[field], unlocked[field])
        normal_env, unlocked_env = normal["companion_environment"], unlocked["companion_environment"]
        self.assertEqual(normal_env["CTR_UNLOCK_ALL"], "false")
        self.assertEqual(unlocked_env["CTR_UNLOCK_ALL"], "true")
        self.assertNotEqual(normal_env["DATA_DIR"], unlocked_env["DATA_DIR"])
        self.assertEqual(normal_env["CTR_LOCAL_WEAK_TOKEN"], "1")

    def test_http_routes_binary_body_headers_and_udp_fixture(self):
        publisher = http.server.ThreadingHTTPServer(("127.0.0.2", self.auth_port), EchoPublisher)
        publisher_thread = threading.Thread(target=publisher.serve_forever, daemon=True)
        publisher_thread.start()
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as udp:
            udp.bind(("127.0.0.1", 0))
            udp.settimeout(12)
            self.env["TEST_UDP_PORT"] = str(udp.getsockname()[1])
            errors = []
            def echo():
                try:
                    body, source = udp.recvfrom(256)
                    udp.sendto(body, source)
                except OSError as error:
                    errors.append(str(error))
            thread = threading.Thread(target=echo, daemon=True)
            thread.start()
            try:
                result = self.invoke(mode="full")
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout +
                                 ((self.root / "host-error.json").read_text() if (self.root / "host-error.json").exists() else ""))
                self.assertTrue(wait_json(self.root / "host.json")["http_and_udp_passed"])
                self.assert_clean_shutdown()
            finally:
                publisher.shutdown()
                publisher.server_close()
                publisher_thread.join(3)
                thread.join(3)
            self.assertFalse(errors)

    def test_abrupt_bridge_exit_kills_host_and_descendant(self):
        config = self.root / "fixture.ini"
        config.write_text(self.config(), encoding="utf-8")
        environment = dict(self.env, TEST_HOST_MODE="hold")
        process = subprocess.Popen([str(ARGS.bridge), "--config", str(config)], env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        pids = []
        try:
            child = wait_json(self.root / "descendant.json")
            host = wait_json(self.root / "host.json")
            pids = [host["pid"], child["pid"]]
            self.assertTrue(all(alive(pid) for pid in pids))
            process.kill()
            process.communicate(timeout=10)
            end = time.monotonic() + 5
            while any(alive(pid) for pid in pids) and time.monotonic() < end:
                time.sleep(0.025)
            self.assertFalse(any(alive(pid) for pid in pids), "Supervised fixture process survived bridge termination")
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)
            for pid in pids:
                stop_fixture(pid)

    def test_bodyless_publisher_response_metadata(self):
        with self.publisher(BodylessPublisher) as publisher, self.running_bridge():
            for method, path, status, expected_length in [
                ("HEAD", "/representation", 200, "123"),
                ("HEAD", "/large-representation", 200, "12345678"),
                ("GET", "/not-modified", 304, "123"),
                ("GET", "/large-not-modified", 304, "12345678"),
                ("GET", "/not-modified-no-length", 304, None),
                ("GET", "/no-content", 204, None),
            ]:
                with self.subTest(method=method, path=path):
                    connection = http.client.HTTPConnection("127.0.0.2", self.http_port, timeout=5)
                    try:
                        connection.request(method, path, headers={"Host": "publisher.fixture.invalid"})
                        response = connection.getresponse()
                        self.assertEqual(response.status, status)
                        self.assertEqual(response.getheader("Content-Length"), expected_length)
                        self.assertEqual(response.read(), b"")
                    finally:
                        connection.close()
            self.assertEqual(len(publisher.requests), 6)

    def test_ambiguous_request_framing_is_rejected_before_forwarding(self):
        cases = [
            ("duplicate length", b"Content-Length: 1\r\nContent-Length: 2\r\n", b"ab"),
            ("length and encoding", b"Content-Length: 0\r\nTransfer-Encoding: chunked\r\n", b"0\r\n\r\n"),
            ("duplicate encoding", b"Transfer-Encoding: chunked\r\nTransfer-Encoding: identity\r\n", b"0\r\n\r\n"),
            ("duplicate host", b"Host: other.fixture.invalid\r\nContent-Length: 0\r\n", b""),
            ("length list", b"Content-Length: 0, 1\r\n", b"x"),
            ("empty length and encoding", b"Content-Length:\r\nTransfer-Encoding: chunked\r\n", b"0\r\n\r\n"),
            ("length and empty encoding", b"Content-Length: 0\r\nTransfer-Encoding:\r\n", b""),
        ]
        with self.publisher(BodylessPublisher) as publisher, self.running_bridge() as process:
            for name, headers, body in cases:
                with self.subTest(framing=name):
                    with socket.create_connection(("127.0.0.2", self.http_port), timeout=5) as connection:
                        connection.sendall(b"POST /framing HTTP/1.1\r\nHost: publisher.fixture.invalid\r\n" +
                                           headers + b"Connection: close\r\n\r\n" + body)
                        response = bytearray()
                        while True:
                            chunk = connection.recv(4096)
                            if not chunk:
                                break
                            response.extend(chunk)
                            self.assertLessEqual(len(response), 65536)
                    self.assertTrue(response.startswith(b"HTTP/1.1 400 "), response[:80])
            self.assertEqual(publisher.requests, [], "Invalid request reached the publisher")
            self.assertFalse(any(event["event"] == "webapi" for event in self.events()))
            self.assertIsNone(process.poll(), "Malformed request stopped the bridge")

    def test_companion_readiness_loss_stops_signed_in_host(self):
        self.env["TEST_PROVIDER_DROP_READY"] = "1"
        result = self.invoke(mode="hold", timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Provider or publisher became unavailable", result.stderr)
        self.assertEqual(len([e for e in self.events() if e["event"] == "bind_endpoint" and e["status"] == 0]), 1)
        host = wait_json(self.root / "host.json")
        child = wait_json(self.root / "descendant.json")
        pids = [host["pid"], child["pid"]]
        try:
            self.assertFalse(any(alive(pid) for pid in pids), "Host survived lost publisher readiness")
            self.assert_clean_shutdown()
        finally:
            for pid in pids:
                stop_fixture(pid)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ["bridge", "provider", "missing-provider", "host", "work-root"]:
        parser.add_argument("--" + key, type=Path, required=True)
    ARGS = parser.parse_args()
    for key in ["bridge", "provider", "missing_provider", "host", "work_root"]:
        setattr(ARGS, key, getattr(ARGS, key).resolve())
    ARGS.work_root.mkdir(parents=True, exist_ok=True)
    unittest.main(argv=[__file__], verbosity=2)
