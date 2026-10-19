"""Independent bridge process fixtures; no Steam, server binary, native launcher or game runs."""
import argparse
import contextlib
import ctypes
import http.client
import http.server
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest


def unused_port(address):
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


PATCH_XML = """<?xml version='1.0' encoding='utf-8'?>
<Patch><TitleID><ID>CUSA13795</ID></TitleID><Metadata Title="Crash Team Racing Nitro-Fueled" Name="CTR:NF Server Signature Patch" Author="fixture" PatchVer="0.1" AppVer="01.21" AppElf="eboot.bin" isEnabled="false" Note="fixture"><PatchList><Line Type="bytes" Address="0x00413ec0" Value="909090909090" /></PatchList></Metadata></Patch>
"""
PATCH_KEY = "CrashTeamRacingNitroFueled.xml/CTR:NF Server Signature Patch"
# Fixed internal server auth port; the fixtures use their own loopback address.
AUTH_PORT = 8460
ADDRESS = "127.0.0.77"
EXE = ".exe" if os.name == "nt" else ""


@unittest.skipUnless(os.name == "nt", "the native adapter launches only on Windows")
class BridgeIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bridge fixtures ", dir=ARGS.work_root)
        self.addCleanup(self.cleanup_fixture)
        self.root = Path(self.temp.name)
        # The installed layout: bridge, native launcher and server at the port root.
        self.bridge = self.root / ("ctrnf-p2p" + EXE)
        shutil.copy2(ARGS.bridge, self.bridge)
        self.desktop = self.root / ("ctrnf-p2p-desktop" + EXE)
        shutil.copy2(ARGS.desktop, self.desktop)
        shutil.copy2(ARGS.host, self.root / "CTR-NitroFueled-PC.exe")
        shutil.copy2(ARGS.host, self.root / ("demonware-server" + EXE))
        (self.root / "lab").mkdir()
        (self.root / "patches").mkdir()
        (self.root / "patches" / "CrashTeamRacingNitroFueled.xml").write_text(PATCH_XML, encoding="utf-8")
        (self.root / "patches.json").write_text(json.dumps({"enabled": [PATCH_KEY], "disabled": []}), encoding="utf-8")
        self.http_port = unused_port(ADDRESS)
        self.env = {key: value for key, value in os.environ.items()
                    if not key.upper().startswith(("TEST_", "BB_", "CTR_", "OSW_", "NEXTENDO_", "SHADNET_"))}
        self.env.update(TEST_CASE_ROOT=str(self.root), TEST_PROVIDER_LOG=str(self.root / "provider.jsonl"),
                        BB_ONLINE_STALE_FIXTURE="must-not-reach-host", CTR_STALE_FIXTURE="must-not-reach-host",
                        OSW_STALE_FIXTURE="must-not-reach-host", BB_NATIVE_FIXTURE="kept",
                        bb_user_name="stale-differently-cased")

    def cleanup_fixture(self):
        # Windows may release an exited process's executable after its exit code
        # becomes observable. Retry cleanup briefly without hiding a locked file.
        end = time.monotonic() + 3
        while True:
            try:
                self.temp.cleanup()
                return
            except PermissionError:
                if time.monotonic() >= end:
                    raise
                time.sleep(0.05)

    def config(self, *, provider=None, lab=True, name="Fixture !+", unlock=False):
        # steam.library names the bridge binary as inert fixture input; the fake
        # provider never loads it. No real user-supplied Steam library is touched.
        return f"""[platform]
provider = steam
library = {json.dumps(str(provider or ARGS.provider))}
[steam]
app_id = 876543
library = {json.dumps(self.bridge.name)}
[game]
host = native
[server]
unlock_all = {str(unlock).lower()}
[session]
realm = fixture-realm
[network]
address = {ADDRESS}
http_port = {self.http_port}
""" + (f"""[lab]
enabled = true
account_id = 123456789
root = {json.dumps(str(self.root / 'lab'))}
online_id = {json.dumps(name)}
""" if lab else "")

    def invoke(self, config=None, arguments=(), *, mode="early", timeout=15, launcher=None):
        path = self.root / "fixture.ini"
        path.write_text(config or self.config(), encoding="utf-8")
        environment = dict(self.env, TEST_HOST_MODE=mode)
        if launcher:
            environment["TEST_LAUNCHER_MODE"] = launcher
        return subprocess.run([str(self.bridge), "--config", str(path), *arguments],
                              env=environment, capture_output=True, text=True,
                              timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)

    def events(self):
        return [json.loads(line) for line in (self.root / "provider.jsonl").read_text().splitlines()]

    def assert_clean_shutdown(self):
        self.assertEqual([entry["event"] for entry in self.events()][-2:], ["stop", "destroy"])

    def supervised_pids(self):
        pids = []
        for name in ["launcher.json", "host.json", "descendant.json", "restarted.json"]:
            path = self.root / name
            if path.exists():
                pids.append(json.loads(path.read_text())["pid"])
        return pids

    def assert_tree_stopped(self):
        pids = self.supervised_pids()
        self.assertTrue(pids)
        end = time.monotonic() + 5
        while any(alive(pid) for pid in pids) and time.monotonic() < end:
            time.sleep(0.025)
        self.assertFalse(any(alive(pid) for pid in pids), "A supervised fixture process survived the session")

    @contextlib.contextmanager
    def running_bridge(self, config_text=None):
        config = self.root / "fixture.ini"
        config.write_text(config_text or self.config(), encoding="utf-8")
        process = subprocess.Popen([str(self.bridge), "--config", str(config)],
                                   env=dict(self.env, TEST_HOST_MODE="hold"),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            wait_json(self.root / "host.json")
            wait_json(self.root / "descendant.json")
            self.assertIsNone(process.poll(), "Bridge exited before HTTP fixture")
            yield process
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)
            for pid in self.supervised_pids():
                stop_fixture(pid)

    def test_octr_private_psn_stream_preserves_acknowledgement_and_identity(self):
        # Existence-only prerequisite; the synthetic host never loads this file.
        (self.root / "psn-bridge-backend.dll").write_bytes(b"inert fixture")
        with self.running_bridge(self.config().replace("host = native", "host = octr")):
            launch = wait_json(self.root / "launcher.json")
            self.assertEqual(launch["online_enabled"], "1")
            self.assertEqual(Path(launch["psn_backend"]), self.root / "psn-bridge-backend.dll")
            config = json.loads(launch["psn_config"])
            self.assertEqual(config["url"], f"http://{ADDRESS}:{self.http_port}")
            def call(path, payload=None, authorized=True):
                connection = http.client.HTTPConnection(ADDRESS, self.http_port, timeout=5)
                try:
                    headers = {"Authorization": "Bearer " + config["token"]} if authorized else {}
                    body = json.dumps(payload) if payload is not None else None
                    connection.request("POST" if payload is not None else "GET", path, body, headers)
                    response = connection.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    connection.close()
            self.assertEqual(call("/psn/v1/info", authorized=False)[0], 403)
            status, info = call("/psn/v1/info")
            self.assertEqual(status, 200)
            self.assertEqual(info["accountId"], "123456789")
            status, first = call("/psn/v1/events?after=0")
            self.assertEqual(status, 200)
            self.assertEqual(call("/psn/v1/events?after=0")[1], first)
            event = first["events"][0]
            self.assertEqual(event["event"]["from"]["accountId"], "76561198012345679")
            self.assertEqual(event["event"]["kind"], "invitationAccepted")
            self.assertEqual(call(f'/psn/v1/events?after={event["sequence"]}')[1]["events"], [])
            self.assertEqual(call("/psn/v1/events?after=0")[0], 409)
            status, token = call("/psn/v1/token", {"kind": 1, "client_id": "fixture", "scope": "openid"})
            self.assertEqual(status, 200)
            self.assertEqual(token["token"], "osw-local-fixture")
            companion = next(entry for entry in self.events() if entry["event"] == "create" and entry["companion"])
            self.assertEqual(companion["companion_environment"]["CTR_LOCAL_WEAK_TOKEN"], "0")

    @contextlib.contextmanager
    def server(self, handler):
        server = http.server.ThreadingHTTPServer((ADDRESS, AUTH_PORT), handler)
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
        invalid_path = self.invoke(arguments=("--config", "non-ascii-\u00e8.ini", "--check"))
        self.assertEqual(invalid_path.returncode, 1)
        self.assertIn("Configuration path must be printable ASCII", invalid_path.stderr)
        for before, after in [
            ("provider = steam", "provider = unsupported"),
            ("unlock_all = false", "unlock_all = 1"),
            ("app_id = 876543", "app_id = 0"),
            ("[server]", "[server]\nweak_admission = true"),
            ("[server]", "[server]\nsigning_key = key.pem"),
            ("[game]", "[game]\ngame_dir = orig/CUSA13795"),
            ("[network]", "[network]\ngame_address = 127.0.0.1"),
            ("[game]", "[unknown]"),
            ("[game]", "[player]\nonline_id = Alice\n[game]"),
        ]:
            with self.subTest(setting=after):
                failed = self.invoke(self.config().replace(before, after), arguments=("--check",))
                self.assertNotEqual(failed.returncode, 0)
                self.assertIn("ctrnf-p2p:", failed.stderr)
        self.assertFalse((self.root / "launcher.json").exists())
        self.assertFalse((self.root / "provider.jsonl").exists())

    def test_signature_patch_diagnostic_precedes_any_launch(self):
        selection = self.root / "patches.json"
        patch = self.root / "patches" / "CrashTeamRacingNitroFueled.xml"
        cases = [
            ("wrong write", lambda: patch.write_text(PATCH_XML.replace("0x00413ec0", "0x00413ec4"))),
            ("other version", lambda: patch.write_text(PATCH_XML.replace('AppVer="01.21"', 'AppVer="01.20"'))),
            ("commented write", lambda: patch.write_text(PATCH_XML.replace('<Line ', '<!-- <Line ').replace('/></PatchList>', '/> --></PatchList>'))),
            ("CDATA write", lambda: patch.write_text(PATCH_XML.replace('<Line ', '<![CDATA[<Line ').replace('/></PatchList>', '/>]]></PatchList>'))),
            ("commented metadata", lambda: patch.write_text(PATCH_XML.replace('<Metadata ', '<!-- <Metadata ').replace('</Metadata>', '</Metadata> -->'))),
            ("commented title", lambda: patch.write_text(PATCH_XML.replace('<ID>CUSA13795</ID>', '<!-- <ID>CUSA13795</ID> --><ID>CUSA00000</ID>'))),
            ("malformed tail", lambda: patch.write_text(PATCH_XML.replace('</Patch>', '</Mismatch>'))),
            ("second root", lambda: patch.write_text(PATCH_XML + '<Patch/>')),
            ("unsupported extra write", lambda: patch.write_text(PATCH_XML.replace('</PatchList>', '<Line Type="unknown" Address="0x00413ec0" Value="00" /></PatchList>'))),
            ("doctype", lambda: patch.write_text(PATCH_XML.replace('<Patch>', '<!DOCTYPE Patch [<!ENTITY fixture "unused">]><Patch>'))),
            ("no file", lambda: patch.unlink()),
        ]
        for name, damage in cases:
            with self.subTest(case=name):
                selection.write_text(json.dumps({"enabled": [PATCH_KEY]}))
                patch.write_text(PATCH_XML)
                damage()
                for arguments in [("--check",), ()]:
                    result = self.invoke(arguments=arguments)
                    self.assertEqual(result.returncode, 1, result.stdout)
                    self.assertIn("Signature patch", result.stderr)
                self.assertFalse((self.root / "launcher.json").exists())
                self.assertFalse((self.root / "provider.jsonl").exists())
        # BB_DATA_DIR relocates patches.json exactly as the native launcher script does.
        selection.unlink()
        patch.write_text(PATCH_XML)
        (self.root / "native data").mkdir()
        self.env["BB_DATA_DIR"] = "native data"
        self.assertNotEqual(self.invoke(arguments=("--check",)).returncode, 0)
        (self.root / "native data" / "patches.json").write_text(json.dumps({"enabled": [PATCH_KEY]}))
        relocated = self.invoke(arguments=("--check",))
        self.assertEqual(relocated.returncode, 0, relocated.stderr)
        # Missing launcher.
        (self.root / "CTR-NitroFueled-PC.exe").unlink()
        missing = self.invoke(arguments=("--check",))
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("Native launcher", missing.stderr)

    def test_first_launch_enables_only_required_patch_and_is_idempotent(self):
        selection = self.root / "patches.json"
        original = {
            "version": 1,
            "enabled": ["Other.xml/Keep enabled"],
            "disabled": ["Other.xml/Keep disabled", PATCH_KEY, PATCH_KEY],
            "preferences": {"window": [1280, 720], "label": "caf\u00e9", "remember": True},
        }
        selection.write_text(json.dumps(original), encoding="utf-8")
        before = selection.read_bytes()
        checked = self.invoke(arguments=("--check",))
        self.assertEqual(checked.returncode, 1)
        self.assertEqual(selection.read_bytes(), before, "Read-only check changed patch settings")
        self.assertFalse((self.root / "provider.jsonl").exists())
        result = self.invoke(mode="delayed")
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = dict(original, enabled=original["enabled"] + [PATCH_KEY],
                        disabled=["Other.xml/Keep disabled"])
        self.assertEqual(json.loads(selection.read_text(encoding="utf-8")), expected)
        self.assertIn("patch enabled", result.stdout)
        saved = selection.read_bytes()
        timestamp = 1_600_000_000_000_000_000
        os.utime(selection, ns=(timestamp, timestamp))
        repeated = self.invoke(mode="delayed")
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(selection.read_bytes(), saved)
        self.assertEqual(selection.stat().st_mtime_ns, timestamp,
                         "Already enabled configuration was rewritten")
        self.assertNotIn("patch enabled", repeated.stdout)
        self.assertEqual(self.invoke(arguments=("--check",)).returncode, 0)

    def test_first_launch_creates_selection_and_resolves_disabled_conflict(self):
        selection = self.root / "patches.json"
        for initial in [None, {}, {"enabled": [PATCH_KEY], "disabled": [PATCH_KEY, "Other.xml/Off"]}]:
            with self.subTest(initial=initial):
                if initial is None:
                    selection.unlink(missing_ok=True)
                else:
                    selection.write_text(json.dumps(initial), encoding="utf-8")
                result = self.invoke(mode="delayed")
                self.assertEqual(result.returncode, 0, result.stderr)
                actual = json.loads(selection.read_text())
                self.assertEqual(actual["enabled"], [PATCH_KEY])
                self.assertNotIn(PATCH_KEY, actual.get("disabled", []))
                if initial and "disabled" in initial:
                    self.assertEqual(actual["disabled"], ["Other.xml/Off"])

    def test_auto_patch_respects_native_path_overrides(self):
        standard = self.root / "patches.json"
        original = standard.read_bytes()
        data = self.root / "native data" / "first run"
        self.env["BB_DATA_DIR"] = "native data/first run"
        result = self.invoke(mode="delayed")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(PATCH_KEY, json.loads((data / "patches.json").read_text())["enabled"])
        custom = self.root / "custom native"
        custom.mkdir()
        xml_dir = self.root / "custom patches"
        xml_dir.mkdir()
        (xml_dir / "CrashTeamRacingNitroFueled.xml").write_text(PATCH_XML, encoding="utf-8")
        custom_selection = custom / "selections.json"
        custom_selection.write_text('{"other":true,"disabled":[]}', encoding="utf-8")
        self.env.update(BB_PATCHES_CONFIG="custom native/selections.json", BB_PATCHES_DIR="custom patches")
        (self.root / "patches" / "CrashTeamRacingNitroFueled.xml").unlink()
        result = self.invoke(mode="delayed")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(custom_selection.read_text()),
                         {"other": True, "disabled": [], "enabled": [PATCH_KEY]})
        self.assertEqual(standard.read_bytes(), original, "Unselected configuration changed")

    def test_auto_patch_refuses_invalid_settings_without_replacing_them(self):
        selection = self.root / "patches.json"
        for text in ['{broken', '[]', '{"enabled":null}', '{"disabled":"wrong"}',
                     '{"enabled":[7]}', '{"enabled":[],"other":1,"other":2}',
                     '{"enabled":[],"nested":{"key":1,"key":2}}']:
            with self.subTest(text=text):
                selection.write_text(text, encoding="utf-8")
                before = selection.read_bytes()
                result = self.invoke()
                self.assertEqual(result.returncode, 1)
                self.assertEqual(selection.read_bytes(), before)
                self.assertFalse((self.root / "provider.jsonl").exists())
                self.assertFalse((self.root / "launcher.json").exists())
        selection.write_text('{"enabled":[],"keep":"original"}', encoding="utf-8")
        before = selection.read_bytes()
        patch = self.root / "patches" / "CrashTeamRacingNitroFueled.xml"
        patch.write_text(PATCH_XML.replace("0x00413ec0", "0x00413ec4"), encoding="utf-8")
        self.assertEqual(self.invoke().returncode, 1)
        self.assertEqual(selection.read_bytes(), before, "Unsupported XML changed selection")
        self.assertFalse((self.root / "provider.jsonl").exists())

    def test_auto_patch_unwritable_file_preserves_settings_and_stops_launch(self):
        selection = self.root / "patches.json"
        selection.write_text('{"enabled":[],"keep":"original"}', encoding="utf-8")
        before = selection.read_bytes()
        selection.chmod(0o444)
        try:
            result = self.invoke()
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertEqual(selection.read_bytes(), before)
            self.assertFalse((self.root / "provider.jsonl").exists())
            self.assertFalse((self.root / "launcher.json").exists())
        finally:
            selection.chmod(0o666)

    def test_probe_does_not_enable_patch(self):
        selection = self.root / "patches.json"
        selection.write_text('{"enabled":[],"disabled":[]}', encoding="utf-8")
        before = selection.read_bytes()
        result = self.invoke(arguments=("--probe",))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(selection.read_bytes(), before)
        self.assertFalse((self.root / "launcher.json").exists())

    def test_desktop_has_no_console_logs_and_supervises_its_tree(self):
        (self.root / "patches.json").unlink()
        config = self.root / 'desktop.ini'
        config.write_text(self.config(), encoding='utf-8')
        process = subprocess.Popen([str(self.desktop), '--config', str(config)],
                                   env=dict(self.env, TEST_HOST_MODE='hold', TEST_LAUNCHER_LINGER='1'),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            wait_json(self.root / 'host.json')
            wait_json(self.root / 'descendant.json')
            self.assertEqual(json.loads((self.root / "patches.json").read_text())["enabled"], [PATCH_KEY])
            # An independent console-free process tries attaching to the bridge.
            # ERROR_INVALID_HANDLE (6) is Windows' response when it has no console.
            inspector = subprocess.run([sys.executable, '-c',
                'import ctypes,sys; k=ctypes.WinDLL("kernel32",use_last_error=True); '
                'k.FreeConsole(); attached=k.AttachConsole(int(sys.argv[1])); '
                'error=ctypes.get_last_error(); k.FreeConsole(); '
                'sys.exit(0 if not attached and error==6 else 1)', str(process.pid)],
                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
            self.assertEqual(inspector.returncode, 0, 'Desktop entry point owns a console')
            end = time.monotonic() + 5
            while not any(e['event'] == 'bind_endpoint' and e['status'] == 0 for e in self.events()):
                self.assertLess(time.monotonic(), end, 'Desktop did not register fixture endpoint')
                time.sleep(0.025)
            stop_fixture(wait_json(self.root / 'host.json')['pid'])
            self.assertEqual(process.wait(timeout=8), 0)
            log = (self.root / 'ctrnf-p2p/bridge.log').read_text(encoding='utf-8')
            self.assertIn('Native launcher started', log)
            self.assertIn('Game exited; the supervised session is finished.', log)
            self.assert_tree_stopped()
            self.assert_clean_shutdown()
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            for pid in self.supervised_pids():
                stop_fixture(pid)

    def test_portable_diagnostics_do_not_need_launch_prerequisites(self):
        (self.root / "CTR-NitroFueled-PC.exe").unlink()
        (self.root / "patches.json").unlink()
        result = self.invoke(arguments=("--probe",))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_clean_shutdown()

    def test_missing_provider_and_required_symbol_fail_before_host(self):
        absent = self.invoke(self.config(provider=self.root / "does-not-exist.dll"))
        self.assertNotEqual(absent.returncode, 0)
        self.assertIn("platform.library", absent.stderr)
        incomplete = self.invoke(self.config(provider=ARGS.missing_provider))
        self.assertNotEqual(incomplete.returncode, 0)
        self.assertIn("osw_get_persona_name", incomplete.stderr)
        self.assertFalse((self.root / "launcher.json").exists())
        self.assertFalse((self.root / "provider.jsonl").exists())

    def test_probe_and_persona_bootstrap_do_not_launch_host(self):
        result = self.invoke(self.config(lab=False), arguments=("--probe",))
        self.assertEqual(result.returncode, 0, result.stderr)
        creates = [e for e in self.events() if e["event"] == "create"]
        self.assertEqual(len(creates), 2)
        self.assertFalse(creates[0]["companion"])
        self.assertEqual(creates[1]["online_id"], "Fixture _!")
        self.assertTrue(creates[1]["companion"])
        self.assertEqual((creates[1]["title"], creates[1]["build"], creates[1]["realm"]), ("5760", "01.21", "fixture-realm"))
        self.assertEqual([e["value"] for e in self.events() if e["event"] == "appid"], [876543, 876543])
        self.assertEqual(len([e for e in self.events() if e["event"] == "defer_endpoint"]), 1)
        self.assertFalse(any(e["event"] == "bind_endpoint" for e in self.events()))
        self.assertFalse((self.root / "launcher.json").exists())
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
        self.assertFalse((self.root / "launcher.json").exists())
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
                self.assertFalse((self.root / "launcher.json").exists())
                self.assert_clean_shutdown()

    def test_launcher_receives_only_online_identity(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 3, result.stderr)
        report = wait_json(self.root / "launcher.json")
        self.assertEqual(report["arguments"], [])
        self.assertEqual(Path(report["cwd"]).resolve(), self.root.resolve())
        self.assertEqual(report["online_id"], report["user_name"])
        self.assertEqual(report["online_id"], "Fixture !+")
        self.assertEqual((report["online_server"], report["http_port"]), (ADDRESS, str(self.http_port)))
        self.assertEqual(report["allow"], "127.0.0.1")
        self.assertEqual(report["native_fixture"], "kept")
        self.assertTrue(report["private_inheritance_removed"])
        self.assertTrue(report["native_settings_absent"])
        self.assertTrue(report["account_matches_fixture"])
        self.assertFalse(any(alive(pid) for pid in self.supervised_pids()))
        self.assert_clean_shutdown()

    def test_game_grandchild_endpoint_registers_and_its_exit_ends_session(self):
        self.env["TEST_LAUNCHER_LINGER"] = "1"
        result = self.invoke(mode="delayed", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Game exited", result.stdout)
        report = wait_json(self.root / "host.json")
        self.assertTrue(report["endpoint_ready"])
        binds = [e for e in self.events() if e["event"] == "bind_endpoint"]
        self.assertEqual(binds, [{"event": "bind_endpoint", "address": "127.0.0.1", "port": report["udp_port"], "status": 0}])
        self.assert_tree_stopped()
        self.assert_clean_shutdown()

    def test_native_process_tree_receives_configured_steam_association(self):
        self.env.update(steamappid="111", STEAMGAMEID="222")
        for lab in (False, True):
            with self.subTest(lab=lab):
                result = self.invoke(self.config(lab=lab))
                self.assertEqual(result.returncode, 3, result.stderr)
                expected = "" if lab else "876543"
                for name in ("launcher.json", "host.json"):
                    report = wait_json(self.root / name)
                    self.assertEqual(report["steam_app_id"], expected)
                    self.assertEqual(report["steam_game_id"], expected)
                self.assertFalse(any(alive(pid) for pid in self.supervised_pids()))
                self.assert_clean_shutdown()

    def test_apply_and_restart_ends_session_without_survivors(self):
        result = self.invoke(mode="restart", launcher="restart", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Game exited", result.stdout)
        self.assertEqual(len([e for e in self.events() if e["event"] == "bind_endpoint" and e["status"] == 0]), 1)
        self.assert_tree_stopped()
        self.assert_clean_shutdown()

    def test_ambiguous_or_wrong_address_udp_endpoint_fails_closed(self):
        for mode, launcher in [("ambiguous", None), ("wrong-address", None), ("hold", "two-owners")]:
            with self.subTest(mode=mode, launcher=launcher):
                result = self.invoke(mode=mode, launcher=launcher)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("UDP", result.stderr)
                self.assert_tree_stopped()
                self.assert_clean_shutdown()

    def test_rejected_endpoint_registration_stops_owned_host(self):
        self.env["TEST_ENDPOINT_REJECT"] = "1"
        result = self.invoke(mode="hold")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("endpoint registration", result.stderr)
        self.assert_tree_stopped()
        self.assert_clean_shutdown()

    def test_closed_or_changed_owned_udp_endpoint_stops_session(self):
        for mode in ["closed", "changed"]:
            with self.subTest(mode=mode):
                result = self.invoke(mode=mode)
                self.assertEqual(result.returncode, 1, result.stderr)
                report = wait_json(self.root / "host.json")
                if mode == "closed":
                    self.assertIn(f"UDP endpoint is no longer observable (registered port {report['udp_port']})", result.stderr)
                else:
                    self.assertIn(f"UDP endpoint changed from port {report['udp_port']} to {report['changed_udp_port']}", result.stderr)
                self.assertTrue(report["endpoint_ready"])
                self.assert_tree_stopped()
                self.assert_clean_shutdown()

    def test_server_environment_shares_storage_across_economy_modes(self):
        snapshots = []
        for unlocked in [False, True]:
            result = self.invoke(self.config(unlock=unlocked), arguments=("--probe",))
            self.assertEqual(result.returncode, 0, result.stderr)
            snapshots.append([e for e in self.events() if e["event"] == "create"][-1])
        normal, unlocked = snapshots
        for field in ["title", "build", "realm", "companion_working_dir"]:
            self.assertEqual(normal[field], unlocked[field])
        normal_env, unlocked_env = normal["companion_environment"], unlocked["companion_environment"]
        self.assertEqual(normal_env["CTR_UNLOCK_ALL"], "false")
        self.assertEqual(unlocked_env["CTR_UNLOCK_ALL"], "true")
        self.assertEqual(normal_env["DATA_DIR"], unlocked_env["DATA_DIR"])
        server = (self.root / "demonware-server").resolve()
        self.assertEqual(Path(normal["companion_working_dir"]).resolve(), server)
        self.assertEqual(Path(normal_env["DATA_DIR"]).resolve(), server / "data")
        self.assertEqual(Path(normal_env["OSW_COMPANION_STDERR"]).resolve(), server / "logs" / "server.log")
        self.assertEqual(normal_env["CTR_LOCAL_WEAK_TOKEN"], "1")
        self.assertEqual(normal_env["AUTH_PORT"], str(AUTH_PORT))
        self.assertNotIn("CTR_AUTH_SIGNING_KEY", normal_env)
        self.assertNotIn("PATH", normal_env)
        self.assertTrue((self.root / "ctrnf-p2p").is_dir())

    def test_http_routes_binary_body_headers_and_udp_fixture(self):
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as udp, self.server(EchoPublisher):
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
                thread.join(3)
            self.assertFalse(errors)

    def test_abrupt_bridge_exit_kills_launcher_game_and_descendant(self):
        config = self.root / "fixture.ini"
        config.write_text(self.config(), encoding="utf-8")
        process = subprocess.Popen([str(self.bridge), "--config", str(config)], env=dict(self.env, TEST_HOST_MODE="hold"),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            wait_json(self.root / "descendant.json")
            pids = self.supervised_pids()
            self.assertEqual(len(pids), 3)
            self.assertTrue(all(alive(pid) for pid in pids))
            process.kill()
            process.communicate(timeout=10)
            self.assert_tree_stopped()
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)
            for pid in self.supervised_pids():
                stop_fixture(pid)

    def test_bodyless_server_response_metadata(self):
        with self.server(BodylessPublisher) as server, self.running_bridge():
            for method, path, status, expected_length in [
                ("HEAD", "/representation", 200, "123"),
                ("HEAD", "/large-representation", 200, "12345678"),
                ("GET", "/not-modified", 304, "123"),
                ("GET", "/large-not-modified", 304, "12345678"),
                ("GET", "/not-modified-no-length", 304, None),
                ("GET", "/no-content", 204, None),
            ]:
                with self.subTest(method=method, path=path):
                    connection = http.client.HTTPConnection(ADDRESS, self.http_port, timeout=5)
                    try:
                        connection.request(method, path, headers={"Host": "publisher.fixture.invalid"})
                        response = connection.getresponse()
                        self.assertEqual(response.status, status)
                        self.assertEqual(response.getheader("Content-Length"), expected_length)
                        self.assertEqual(response.read(), b"")
                    finally:
                        connection.close()
            self.assertEqual(len(server.requests), 6)

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
        with self.server(BodylessPublisher) as server, self.running_bridge() as process:
            for name, headers, body in cases:
                with self.subTest(framing=name):
                    with socket.create_connection((ADDRESS, self.http_port), timeout=5) as connection:
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
            self.assertEqual(server.requests, [], "Invalid request reached the server")
            self.assertFalse(any(event["event"] == "webapi" for event in self.events()))
            self.assertIsNone(process.poll(), "Malformed request stopped the bridge")

    def test_server_readiness_or_account_loss_stops_signed_in_host(self):
        for variable in ["TEST_PROVIDER_DROP_READY", "TEST_PROVIDER_ACCOUNT_CHANGE"]:
            with self.subTest(failure=variable):
                for name in ["launcher.json", "host.json", "descendant.json", "provider.jsonl"]:
                    (self.root / name).unlink(missing_ok=True)
                environment = dict(self.env)
                self.env[variable] = "1"
                try:
                    result = self.invoke(mode="hold", timeout=10)
                finally:
                    self.env = environment
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Provider, account or server became unavailable", result.stderr)
                self.assertEqual(len([e for e in self.events() if e["event"] == "bind_endpoint" and e["status"] == 0]), 1)
                wait_json(self.root / "descendant.json")
                try:
                    self.assert_tree_stopped()
                    self.assert_clean_shutdown()
                finally:
                    for pid in self.supervised_pids():
                        stop_fixture(pid)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ["bridge", "desktop", "provider", "missing-provider", "host", "work-root"]:
        parser.add_argument("--" + key, type=Path, required=True)
    ARGS = parser.parse_args()
    for key in ["bridge", "desktop", "provider", "missing_provider", "host", "work_root"]:
        setattr(ARGS, key, getattr(ARGS, key).resolve())
    ARGS.work_root.mkdir(parents=True, exist_ok=True)
    unittest.main(argv=[__file__], verbosity=2)
