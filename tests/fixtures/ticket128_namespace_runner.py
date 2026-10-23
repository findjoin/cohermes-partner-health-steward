"""Frozen verifier-only namespace operator; six fixed methods, no command input.

Each invocation owns fresh filesystem/accounts/default, PID/mount/net/cgroup
namespaces, root-user manager, private D-Bus and journal. Only the named original
unittest method executes; its real result is returned to its parent method.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, text=True, capture_output=True, **kwargs)


def bind(source, target, readonly=True):
    target.mkdir(parents=True, exist_ok=True)
    run(["mount", "--bind", str(source), str(target)])
    if readonly:
        run(["mount", "-o", "remount,bind,ro", str(target)])


_CASE = "tests.test_ticket128_default_deployment.Ticket128DefaultDeploymentVerificationTests."
METHODS = tuple(_CASE + value for value in (
    "test_v128_02_same_publication_live_factory_and_exact_disclosure",
    "test_v128_03_first_bootstrap_and_real_replica_absence",
    "test_v128_04_default_only_complete_program_rollback",
    "test_v128_05_three_real_os_roles_and_no_root_agent_bypass",
    "test_v128_06_g11_single_attempt_native_action_and_original_cursor",
    "test_v128_07_nd12_native_feedback_is_only_an_nd_milestone"))


def safe_relative(value):
    path = Path(value)
    if path.is_absolute() or path.as_posix() != value or '..' in path.parts or '.git' in path.parts:
        raise ValueError('unsafe declared source path')
    return path


def validate_runtime(root):
    manifest = json.loads((root / 'ticket123-runtime-manifest.json').read_text())
    assert manifest['contract'] == 'ticket123-runtime-closure-v1'
    files = []
    for path in sorted(root.rglob('*'), key=lambda p: p.relative_to(root).as_posix()):
        assert not path.is_symlink()
        if path.is_file() and path.name != 'ticket123-runtime-manifest.json':
            files.append({'path': path.relative_to(root).as_posix(), 'sha256': 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()})
    canonical = json.dumps(files, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    assert files == manifest['files']
    assert manifest['closure_digest'] == 'sha256:' + hashlib.sha256(canonical).hexdigest()
    return manifest


def public_runtime_copy(source, destination):
    # Byte-identical PUBLIC code, in owned backing, normalized for low-UID reads.
    # Never chmod/chown/hardlink the source closure or any health material.
    shutil.copytree(source, destination)
    destination.chmod(0o755)
    for path in destination.rglob('*'):
        assert not path.is_symlink()
        if path.is_dir():
            path.chmod(0o755)
        elif path.is_file():
            path.chmod(0o555 if path.stat().st_mode & 0o111 else 0o444)
    validate_runtime(destination)


def host(args):
    assert os.getuid() == os.geteuid() == 0, 'actual host root required'
    assert sys.version_info[:2] == (3, 11), 'parent must use actual closure Python3.11'
    assert args.method in METHODS
    roots = {}
    for key in ('runtime_root', 'verifier_root', 'pinned_root'):
        value = getattr(args, key)
        assert value is not None
        root = value.resolve()
        assert root.is_dir() and root.is_relative_to(Path('/opt')) and not value.is_symlink()
        roots[key] = str(root)
    runtime, verifier, pinned = (Path(roots[key]) for key in ('runtime_root', 'verifier_root', 'pinned_root'))
    assert Path(sys.executable).resolve().is_relative_to(runtime)
    validate_runtime(runtime)
    source = json.loads((runtime.parent / 'logs/source-snapshot.json').read_text())
    for entry in source['files']:
        path = verifier / safe_relative(entry['path'])
        assert path.is_file() and not path.is_symlink()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256'], entry['path']
    own_relative = Path(__file__).resolve().relative_to(verifier).as_posix()
    assert any(entry['path'] == own_relative and entry['sha256'] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest() for entry in source['files'])
    assert run(['git', '-C', str(pinned), 'rev-parse', 'HEAD']).stdout.strip() == '3c27eb6234bf91b8ceee9e9071591b31e9b148cb'
    base = Path(tempfile.mkdtemp(prefix='t128ns-family-', dir='/opt'))
    base.chmod(0o755)
    script = base / 'probe.py'
    shutil.copyfile(Path(__file__).resolve(), script)
    script.chmod(0o600)
    config = dict(roots, method=args.method, source=source,
                  host_net_ns=os.readlink('/proc/self/ns/net'),
                  host_pid_ns=os.readlink('/proc/self/ns/pid'),
                  host_mount_ns=os.readlink('/proc/self/ns/mnt'))
    (base / 'operator-input.json').write_text(json.dumps(config))
    unit = 't128ns-family-' + uuid.uuid4().hex[:12]
    command = ['systemd-run', '--system', '--quiet', '--wait', '--pipe', '--collect',
               '--unit=' + unit, '--property=Delegate=yes', '--property=KillMode=control-group', '--property=RuntimeMaxSec=7320',
               '--', '/usr/bin/env', '-i', 'PATH=/usr/sbin:/usr/bin:/sbin:/bin', 'LANG=C.UTF-8',
               'unshare', '--mount', '--net', '--ipc', '--uts', '--cgroup', '--pid', '--fork',
               '--kill-child', '--propagation', 'private', '/usr/bin/python3', '-I', '-B', str(script), '--init', str(base)]
    shutil.copyfile(runtime / 'ticket123-runtime-manifest.json', base / 'input-runtime-manifest.json')
    result = None
    cleanup_confirmed = False
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=7350)
    finally:
        # Every exit path operates only on this invocation's random SYSTEM unit.
        # RuntimeMaxSec additionally bounds its lifetime if the client is killed.
        cleanup = {}
        try:
            stopped = subprocess.run(['systemctl', '--system', 'stop', unit], text=True, capture_output=True, timeout=15)
            shown = subprocess.run(['systemctl', '--system', 'show', unit, '--property=LoadState,ActiveState,MainPID'], text=True, capture_output=True, timeout=5)
            properties = dict(line.split('=', 1) for line in shown.stdout.splitlines() if '=' in line)
            cleanup.update(stop_exit=stopped.returncode, show_exit=shown.returncode, properties=properties)
            cleanup_confirmed = (shown.returncode == 0 and properties.get('ActiveState') in {'inactive', 'failed'} and properties.get('MainPID', '0') == '0')
        except subprocess.TimeoutExpired:
            cleanup['timeout'] = True
        mounts = [line.split()[4] for line in Path('/proc/self/mountinfo').read_text().splitlines()]
        rootfs = str(base / 'rootfs')
        if any(value == rootfs or value.startswith(rootfs + '/') for value in mounts):
            cleanup_confirmed = False
            cleanup['host_mount_still_present'] = True
        cleanup['confirmed'] = cleanup_confirmed
        (base / 'cleanup.json').write_text(json.dumps(cleanup, indent=2) + '\n')
        if result is not None:
            (base / 'outer.stdout').write_text(result.stdout)
            (base / 'outer.stderr').write_text(result.stderr)
        # No deletion unless the owned unit is stopped and its mounts are absent.
        # The kernel namespace owns bind mounts; never follow/remove host inputs.
        if cleanup_confirmed:
            for name in ('rootfs', 'public-runtime', 'public-verifier'):
                path = base / name
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
    report = {'operator_root': str(base), 'fixture_system_unit': unit, 'method': args.method,
              'child_exit_code': result.returncode, 'operator_cleanup_confirmed': cleanup_confirmed,
              'original_method_executed': (base / 'data/original-test.stderr').is_file()}
    (base / 'operator-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)
    # Original unittest output, bounded; private daemon logs are never dumped.
    print(result.stdout[-16000:], end='', flush=True)
    print(result.stderr[-16000:], end='', file=sys.stderr, flush=True)
    return result.returncode if cleanup_confirmed else 1

def init(base):
    assert os.getpid() == 1, "internal init must be private PID1"
    os.umask(0o022)
    config = json.loads((base / "operator-input.json").read_text())
    assert config["method"] in METHODS
    # PID 1 in a fresh PID namespace; host proc is replaced before any daemon.
    root = base / "rootfs"
    root.mkdir(mode=0o755)
    # chroot root must itself be a mountpoint for inner MS_PRIVATE remount.
    run(["mount", "--bind", str(root), str(root)])
    for name in ("usr", "lib", "lib64", "bin", "sbin", "etc", "root", "opt", "home",
                 "run", "tmp", "var", "dev", "proc", "sys"):
        (root / name).mkdir(mode=0o755)
    for name in ("usr", "lib", "lib64", "bin", "sbin"):
        source = Path("/") / name
        if source.is_dir():
            bind(source, root / name)
    # Do not expose the actual installed Hermes tree, configs or credentials.
    empty = base / "empty-local"
    empty.mkdir()
    if (root / "usr/local").is_dir():
        bind(empty, root / "usr/local")
    data = base / "data"
    data.mkdir(mode=0o755)
    (data / "backing-root.txt").write_text(str(base) + "\n")
    bind(data, root / "run/t128", readonly=False)
    # Fixed default root-user service context and the verifier's short address
    # are two physical paths to the same owned runtime/bus, never the host bus.
    (data / "runtime").mkdir(mode=0o700)
    bind(data / "runtime", root / "run/user/0", readonly=False)
    hermes = base / "default-home"
    hermes.mkdir(mode=0o700)
    bind(hermes, root / "root/.hermes", readonly=False)
    (hermes / ".ticket128-verifier-only").write_text("/run/t128\n")
    etc = root / "etc"
    (etc / "passwd").write_text("root:x:0:0:root:/root:/bin/sh\nnobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\n")
    (etc / "group").write_text("root:x:0:\nnogroup:x:65534:\n")
    (etc / "shadow").write_text("root:!*:20000:0:99999:7:::\nnobody:!*:20000:0:99999:7:::\n")
    (etc / "gshadow").write_text("root:!::\nnogroup:!::\n")
    (etc / "shadow").chmod(0o600)
    (etc / "gshadow").chmod(0o600)
    (etc / "nsswitch.conf").write_text("passwd: files\ngroup: files\nshadow: files\nhosts: files\n")
    (etc / "hosts").write_text("127.0.0.1 localhost ilinkai.weixin.qq.com novac2c.cdn.weixin.qq.com\n::1 localhost\n")
    (etc / "resolv.conf").write_text("")
    for name in ("machine-id", "ld.so.cache", "login.defs"):
        source = Path("/etc") / name
        if source.is_file():
            shutil.copyfile(source, etc / name)
    for name in ("systemd/user", "default", "skel"):
        (etc / name).mkdir(parents=True, exist_ok=True)
    source = Path("/etc/default/useradd")
    if source.is_file():
        shutil.copyfile(source, etc / "default/useradd")
    (root / "tmp").chmod(0o1777)
    (root / "var/tmp").mkdir(mode=0o1777)
    (root / "var/log").mkdir()
    (root / "run/systemd/system").mkdir(parents=True)
    # The private manager needs the standard OS sources for InaccessiblePaths.
    # Create only this chroot's mode-000 mask nodes; never bind the host's.
    masks = root / "run/systemd/inaccessible"
    masks.mkdir(mode=0o755)
    (masks / "dir").mkdir(mode=0o000)
    (masks / "reg").touch(mode=0o000)
    os.mkfifo(masks / "fifo", mode=0o000)
    os.mknod(masks / "chr", stat.S_IFCHR | 0o000, os.makedev(0, 0))
    os.mknod(masks / "blk", stat.S_IFBLK | 0o000, os.makedev(0, 0))
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as mask_socket:
        mask_socket.bind(str(masks / "sock"))
    (masks / "sock").chmod(0o000)
    run(["mount", "-t", "proc", "proc", str(root / "proc")])
    run(["mount", "-t", "sysfs", "-o", "ro,nosuid,nodev,noexec", "sysfs", str(root / "sys")])
    (root / "sys/fs/cgroup").mkdir(exist_ok=True)
    run(["mount", "-t", "cgroup2", "-o", "nosuid,nodev,noexec", "cgroup2", str(root / "sys/fs/cgroup")])
    for name, major, minor in (("null", 1, 3), ("zero", 1, 5), ("random", 1, 8), ("urandom", 1, 9)):
        run(["mknod", "-m", "666", str(root / "dev" / name), "c", str(major), str(minor)])
    (root / "dev/shm").mkdir(mode=0o1777)
    run(["mount", "-t", "tmpfs", "-o", "size=64m,mode=1777,nosuid,nodev,noexec", "tmpfs", str(root / "dev/shm")])
    (root / "dev/fd").symlink_to("/proc/self/fd")
    (root / "dev/log").symlink_to("/run/systemd/journal/dev-log")
    shutil.copyfile(base / "probe.py", data / "probe.py")
    (data / 'operator-input.json').write_text(json.dumps(config))
    public_runtime_copy(Path(config['runtime_root']), base / 'public-runtime')
    verifier_copy = base / 'public-verifier'
    verifier_copy.mkdir(mode=0o755)
    for entry in config['source']['files']:
        relative = safe_relative(entry['path'])
        source = Path(config['verifier_root']) / relative
        target = verifier_copy / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        target.write_bytes(source.read_bytes())
        target.chmod(0o644)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == entry['sha256']
    for kind, source in (('runtime_root', base / 'public-runtime'), ('verifier_root', verifier_copy), ('pinned_root', Path(config['pinned_root']))):
        target = root / Path(config[kind]).relative_to('/')
        bind(source, target, readonly=True)
    # A second mount namespace keeps /proc/1's namespace distinct from the
    # controller/manager, while PID namespace isolation hides host processes.
    os.chroot(root)
    os.chdir("/")
    command = ["unshare", "--mount", "--propagation", "private",
               "/usr/bin/python3", "-I", "-B", "/run/t128/probe.py", "--inside"]
    child = subprocess.Popen(command)
    status = child.wait()
    # kill(-1) is confined to this freshly created PID namespace.
    try:
        os.kill(-1, signal.SIGKILL)
    except ProcessLookupError:
        pass
    while True:
        try:
            os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            break
        time.sleep(0.01)
    return status


def inside():
    root = Path("/run/t128")
    config = json.loads((root / "operator-input.json").read_text())
    assert config["method"] in METHODS
    assert os.readlink("/proc/self/ns/net") != config["host_net_ns"]
    assert os.readlink("/proc/self/ns/pid") != config["host_pid_ns"]
    runtime = root / "runtime"
    runtime.mkdir(mode=0o700, exist_ok=True)
    units = root / "user-units"
    units.mkdir()
    (units / "t128-fixture.target").write_text("[Unit]\nDescription=Owned namespace primitive probe only\nRequires=dbus.socket dbus.service\nAfter=dbus.socket dbus.service\n")
    address = "unix:path=" + str(runtime / "bus")
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "HOME": "/root",
           "XDG_RUNTIME_DIR": str(runtime), "DBUS_SESSION_BUS_ADDRESS": address,
           "SYSTEMD_UNIT_PATH": str(units) + ":/root/.config/systemd/user:/etc/systemd/user:/usr/lib/systemd/user:/lib/systemd/user"}
    run(["ip", "link", "set", "lo", "up"])
    links = json.loads(run(["ip", "-j", "link", "show"]).stdout)
    assert {item["ifname"] for item in links} == {"lo"}
    assert not run(["ip", "route", "show", "default"]).stdout.strip()
    bus_config = root / "dbus.conf"
    bus_config.write_text('<busconfig><type>session</type><listen>' + address + '</listen><auth>EXTERNAL</auth><policy context="default"><allow user="root"/><allow own="*"/><allow send_destination="*"/><allow receive_sender="*"/></policy></busconfig>')
    children = []
    try:
        (units / "dbus.socket").write_text("[Unit]\nDefaultDependencies=no\n[Socket]\nListenStream=" + str(runtime / "bus") + "\nSocketMode=0600\n")
        (units / "dbus.service").write_text("[Unit]\nDefaultDependencies=no\nRequires=dbus.socket\nAfter=dbus.socket\n[Service]\nType=simple\nExecStart=/usr/bin/dbus-daemon --config-file=" + str(bus_config) + " --address=systemd: --nofork --nopidfile --systemd-activation\nStandardOutput=append:/run/t128/dbus.log\nStandardError=append:/run/t128/dbus.log\n")
        journal = next(path for path in (Path("/usr/lib/systemd/systemd-journald"), Path("/lib/systemd/systemd-journald")) if path.is_file())
        with (root / "journald.log").open("w") as output:
            children.append(subprocess.Popen([str(journal)], env=env, stdout=output, stderr=output))
        with (root / "manager.log").open("w") as output:
            manager = subprocess.Popen(["systemd", "--user", "--unit=t128-fixture.target", "--log-target=console"], env=env, stdout=output, stderr=output)
            children.append(manager)
        deadline = time.monotonic() + 12
        last = ""
        while time.monotonic() < deadline:
            try:
                raw = run(["busctl", "--address=" + address, "call", "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "GetConnectionUnixProcessID", "s", "org.freedesktop.systemd1"], env=env).stdout
                pid = int(raw.split()[-1])
                break
            except subprocess.CalledProcessError as error:
                last = error.stderr
                if manager.poll() is not None:
                    raise RuntimeError("private user manager exited: " + (root / "manager.log").read_text())
                time.sleep(0.1)
        else:
            raise RuntimeError("private manager not registered: " + last)
        assert pid == manager.pid
        assert os.readlink("/proc/self/ns/mnt") == os.readlink("/proc/" + str(pid) + "/ns/mnt")
        assert os.readlink("/proc/self/ns/mnt") != os.readlink("/proc/1/ns/mnt")
        mounts = [line.split() for line in Path("/proc/self/mountinfo").read_text().splitlines()]
        home_mounts = [fields for fields in mounts if fields[4] == "/root/.hermes"]
        assert len(home_mounts) == 1, home_mounts
        backing = Path((root / "backing-root.txt").read_text().strip())
        assert home_mounts[0][3] == str(backing / "default-home"), home_mounts
        (root / "home-mount.json").write_text(json.dumps(home_mounts))
        output_path = root / "private-unit-output.txt"
        run(["systemd-run", "--user", "--wait", "--unit=t128-private-probe", "--property=StandardOutput=append:" + str(output_path), "--", "/usr/bin/printf", "TICKET128_PRIVATE_UNIT\\n"], env=env)
        invocation = run(["systemctl", "--user", "show", "t128-private-probe.service", "--property=InvocationID", "--value"], env=env).stdout.strip()
        assert output_path.read_text().splitlines().count("TICKET128_PRIVATE_UNIT") == 1, output_path.read_text()
        report = {"actual_uid": os.geteuid(), "manager_pid": pid,
                  "controller_mount_ns": os.readlink("/proc/self/ns/mnt"),
                  "manager_mount_ns": os.readlink("/proc/" + str(pid) + "/ns/mnt"),
                  "private_bus_address": address, "interfaces": links,
                  "unit_invocation_id_if_retained": invocation or None,
                  "unit_output_lines": output_path.read_text().splitlines(),
                  "kernel_home_mount": home_mounts[0],
                  "private_shm_mount": [fields for fields in mounts if fields[4] == "/dev/shm"],
                  "private_shm_mode": oct(Path("/dev/shm").stat().st_mode & 0o7777),
                  "private_shm_capacity_bytes": os.statvfs("/dev/shm").f_blocks * os.statvfs("/dev/shm").f_frsize,
                  "private_inaccessible_nodes": {path.name: oct(path.lstat().st_mode)
                      for path in sorted(Path("/run/systemd/inaccessible").iterdir())},
                  "cgroup_view": Path("/proc/self/cgroup").read_text().strip(),
                  "pid_namespace": os.readlink("/proc/self/ns/pid"),
                  "network_namespace": os.readlink("/proc/self/ns/net")}
        report['proof_scope'] = 'operator-preconditions-only-not-a-gate-verdict'
        report['host_net_ns'] = config['host_net_ns']
        report['namespace_backing_root'] = str(backing)
        (root / 'namespace-preconditions.json').write_text(json.dumps(report, indent=2) + '\n')
        env.update(TICKET128_NAMESPACE_WORKER=config['method'], TICKET128_NAMESPACE_ROOT=str(root),
                   TICKET128_NAMESPACE_BACKING_ROOT=str(backing), TICKET128_HOST_NET_NS=config['host_net_ns'],
                   TICKET123_RUNTIME_ROOT=config['runtime_root'], TICKET118_PINNED_HERMES_SOURCE=config['pinned_root'],
                   PYTHONDONTWRITEBYTECODE='1')
        bootstrap = "import os,sys,types,unittest; from pathlib import Path; root=Path(sys.argv[1]); assert sys.version_info[:2]==(3,11); assert os.geteuid()==0; import partner_health_steward as p; assert Path(p.__file__).resolve().is_relative_to(Path(os.environ['TICKET123_RUNTIME_ROOT'])); tests=types.ModuleType('tests'); tests.__path__=[str(root/'tests')]; tests.__package__='tests'; tests.__file__=str(root/'tests/__init__.py'); sys.modules['tests']=tests; suite=unittest.defaultTestLoader.loadTestsFromName(sys.argv[2]); assert suite.countTestCases()==1; result=unittest.TextTestRunner(verbosity=2).run(suite); raise SystemExit(not result.wasSuccessful() or bool(result.skipped))"
        python = str(Path(config['runtime_root']) / 'bin/python3')
        child = subprocess.run([python, '-I', '-B', '-c', bootstrap, config['verifier_root'], config['method']], env=env, text=True, capture_output=True, timeout=7200)
        (root / 'original-test.stdout').write_text(child.stdout)
        (root / 'original-test.stderr').write_text(child.stderr)
        print(child.stdout, end='', flush=True)
        print(child.stderr, end='', file=sys.stderr, flush=True)
        return child.returncode
    finally:
        diagnostics = []
        for argv in (["systemctl", "--user", "show", "dbus.socket", "dbus.service", "t128-fixture.target", "--property=Id,ActiveState,SubState,Result,MainPID,ControlPID,ExecMainCode,ExecMainStatus,Job,Listen", "--no-pager"],
                     ["systemctl", "--user", "list-jobs", "--no-pager"]):
            try:
                observed = subprocess.run(argv, env=env, text=True, capture_output=True, timeout=3)
                diagnostics.append({"argv": argv, "exit_code": observed.returncode, "stdout": observed.stdout[-6000:], "stderr": observed.stderr[-2000:]})
            except subprocess.TimeoutExpired:
                diagnostics.append({"argv": argv, "timeout": True})
        if 'manager' in locals():
            path = Path("/proc/" + str(manager.pid) + "/cgroup")
            diagnostics.append({"manager_cgroup": path.read_text() if path.is_file() else "ABSENT"})
        (root / "private-units.json").write_text(json.dumps(diagnostics, indent=2) + "\n")
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    stage = parser.add_mutually_exclusive_group()
    stage.add_argument("--init", type=Path)
    stage.add_argument("--inside", action="store_true")
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--verifier-root", type=Path)
    parser.add_argument("--pinned-root", type=Path)
    parser.add_argument("--method", choices=METHODS)
    args = parser.parse_args()
    raise SystemExit(init(args.init) if args.init else inside() if args.inside else host(args))
