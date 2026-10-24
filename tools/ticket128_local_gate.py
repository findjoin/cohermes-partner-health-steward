"""Fixed original local verification under the sealed source/runtime closure.

Only the default deployment adapter invokes this tool. Test-only environment
bindings remain outside the published product and never alter the default.
"""
from __future__ import annotations

import os
import sys


def main():
    if len(sys.argv)!=5:
        raise ValueError('fixed local verification arguments required')
    environment={name:os.environ[name] for name in ('PATH','LANG','LC_ALL','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS') if name in os.environ}
    environment.update(PYTHONDONTWRITEBYTECODE='1',TICKET123_RUNTIME_ROOT=sys.argv[1],
        TICKET118_PINNED_HERMES_SOURCE=sys.argv[4])
    os.environ.clear()
    os.environ.update(environment)
    import io,json,unittest
    from contextlib import redirect_stdout,redirect_stderr
    from pathlib import Path
    import partner_health_steward.production_core_service as production
    import partner_health_steward.default_deployment as deployment
    runtime=Path(sys.argv[1]).resolve()
    assert Path(sys.executable).resolve().is_relative_to(runtime)
    assert Path(production.__file__).resolve().parent==runtime/'lib/python3.11/site-packages/partner_health_steward'
    modules=json.loads(sys.argv[3])
    if type(modules) is not list or tuple(modules) not in deployment._LOCAL_MODULES.values():
        raise ValueError('fixed local verification modules required')
    deployment._runtime(runtime,sys.argv[2])
    root,source_identity=deployment._verified_local_sources(runtime,sys.argv[2],modules)
    if Path(__file__).resolve()!=root/'tools/ticket128_local_gate.py':
        raise ValueError('fixed local verification runner required')
    deployment._default_only({'pinned_hermes_root':sys.argv[4]})
    sys.path.insert(0,str(root))
    import tests
    assert Path(tests.__file__).resolve()==root/'tests/__init__.py'
    sys.path.pop(0)
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in modules)
    output=io.StringIO()
    with redirect_stdout(output),redirect_stderr(output):
        result=unittest.TextTestRunner(stream=output,verbosity=0).run(suite)
    print(json.dumps({'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
     'skips':len(result.skipped),'successful':result.wasSuccessful(),
     'failure_tests':[test.id() for test,_ in result.failures],
     'error_tests':[test.id() for test,_ in result.errors],**source_identity},sort_keys=True))
    return 0 if result.wasSuccessful() and result.testsRun>0 and not result.skipped else 1


if __name__=="__main__":
    raise SystemExit(main())
