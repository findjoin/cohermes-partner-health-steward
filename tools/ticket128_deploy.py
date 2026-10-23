"""Fixed default non-diagnostic deployment preparation and ordered execution."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from partner_health_steward import AcceptanceRunContract, DefaultAcceptanceGateExecutor, HostReleaseContract
from partner_health_steward.default_deployment import (
    _ARTIFACTS, _BINDING, _HOME, _bytes, _default_only, _digest, _read_private, _release,
    _safe_directory, _write_private, prepare_default,
)
from partner_health_steward.release_deployment import HermesReleasePublisher


def main(argv=None):
    parser=argparse.ArgumentParser(description='Prepare or run the fixed default acceptance sequence')
    commands=parser.add_subparsers(dest='operation',required=True)
    prepare=commands.add_parser('prepare')
    prepare.add_argument('--release',required=True)
    prepare.add_argument('--run-id',required=True)
    prepare.add_argument('--run-scope',choices=('full','non-diagnostic'),required=True)
    prepare.add_argument('--input')
    commands.add_parser('run')
    args=parser.parse_args(argv)
    if args.operation=='prepare':
        path=Path(args.input) if args.input else _HOME/'.ticket128-raw-input.json'
        _default_only({'release_root':str(Path(args.release).absolute()),'runtime_root':str(path.absolute())})
        facts=_read_private(path)
        result=prepare_default(args.release,args.run_id,args.run_scope,facts)
    else:
        binding=_read_private(_BINDING)
        release=Path(binding['release_root'])
        _release(release)
        manifest=HostReleaseContract().build(HermesReleasePublisher._release_sources(release))
        context=binding['run_context']
        _safe_directory(_ARTIFACTS,create=True)
        report_path=_ARTIFACTS/('report-'+_digest({'run_id':context['run_id']})[7:]+'.json')
        if report_path.exists():context['existing_report']=_read_private(report_path)
        result=AcceptanceRunContract().run(manifest,DefaultAcceptanceGateExecutor(),context).to_wire()
        if not report_path.exists():_write_private(report_path,result,exclusive=True)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':')))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
