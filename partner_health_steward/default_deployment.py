"""The fixed default target adapter for the original acceptance-run seam.

This module owns program installation and opaque execution evidence only. It
never restores health authority from its program backup, and cannot accept a
caller-selected service, profile, command, gate order or business approval.
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import struct
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .acceptance_run import _bound_execution_key, _gates, _approval_gates
from .initialization import stable_digest
from .production_core_service import _validate_active_release, _validate_current_runtime_attestation
from .release_deployment import _strict_json_bytes, _validate_ticket123_runtime_manifest

_HOME = Path('/root/.hermes')
_BINDING = _HOME / '.ticket128-deployment-binding.json'
_TARGET = {'profile': 'default', 'hermes_home': str(_HOME), 'service': 'hermes-gateway.service'}
_PERMITS = _HOME / '.ticket120-deployment-permits'
_ARTIFACTS = _HOME / '.ticket128-execution-artifacts'
_DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')
_OPAQUE = re.compile(r'[^\s\\/]{1,256}\Z')
_STAGES = ('formed','committed','attempted','interface_accepted','delivered','read_or_action','correction','unknown')


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def _digest(value):
    return 'sha256:' + hashlib.sha256(_bytes(value)).hexdigest()


def _now():
    return datetime.now(timezone.utc)


def _time(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timestamp has no timezone')
    return result


def _safe_directory(path, *, create=False, mode=0o700):
    path = Path(path)
    if create:
        path.mkdir(parents=True, mode=mode, exist_ok=True)
    details = path.lstat()
    if (path.is_symlink() or not stat.S_ISDIR(details.st_mode) or details.st_uid != 0
            or stat.S_IMODE(details.st_mode) & 0o022):
        raise ValueError('unsafe fixed target directory')
    return path


def _read_private(path):
    details = path.lstat()
    if (not stat.S_ISREG(details.st_mode) or stat.S_ISLNK(details.st_mode)
            or details.st_uid != 0 or stat.S_IMODE(details.st_mode) != 0o600 or details.st_nlink != 1):
        raise ValueError('unsafe private operation input')
    return _strict_json_bytes(path.read_bytes())


def _write_private(path, value, *, exclusive=False):
    _safe_directory(path.parent, create=True)
    if exclusive:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(_bytes(value)); stream.flush(); os.fsync(stream.fileno())
        return
    descriptor, temporary = tempfile.mkstemp(prefix='.ticket128-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(_bytes(value)); stream.flush(); os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def _default_only(value):
    if type(value) is not dict or value.get('target', _TARGET) != _TARGET:
        raise ValueError('only the fixed default target is permitted')
    for key in ('profile', 'hermes_home', 'service'):
        if key in value and value[key] != _TARGET[key]:
            raise ValueError('only the fixed default target is permitted')
    # Reject an indirect profile selection before reading its configuration.
    for key in ('release_root', 'runtime_root', 'pinned_hermes_root'):
        if key in value:
            path = Path(value[key])
            if (not path.is_absolute() or any(part.startswith('.hermes-') or part == 'hermes-gateway-partner.service'
                    for part in (*path.parts, *path.resolve().parts))):
                raise ValueError('non-default locator is forbidden')


def _release(path):
    path = Path(path)
    _default_only({'release_root': str(path)})
    if path.is_symlink() or not path.is_dir():
        raise ValueError('current distribution is unavailable')
    manifest = _validate_active_release(path)
    if manifest['state'] != 'current':
        raise ValueError('current distribution required')
    return manifest


def _runtime(root, release):
    path = Path(root)
    if path.is_symlink() or not path.is_dir():
        raise ValueError('runtime is unavailable')
    manifest = _validate_ticket123_runtime_manifest(_strict_json_bytes((path / 'ticket123-runtime-manifest.json').read_bytes()))
    declared = {item['path']: item['sha256'] for item in manifest['files']}
    actual = {}
    for item in path.rglob('*'):
        if item.is_symlink(): raise ValueError('runtime symlink is forbidden')
        if item.is_file() and item.name != 'ticket123-runtime-manifest.json':
            actual[item.relative_to(path).as_posix()] = 'sha256:' + hashlib.sha256(item.read_bytes()).hexdigest()
    if declared != actual:
        raise ValueError('actual runtime closure drift')
    _validate_current_runtime_attestation(Path(release), _validate_active_release(Path(release)), manifest)
    return manifest


def prepare_default(release_root, run_id, run_scope, facts):
    """Prepare the bounded local operation input; create no health authority."""
    if run_scope not in {'full', 'non-diagnostic'} or type(run_id) is not str or not _OPAQUE.fullmatch(run_id):
        raise ValueError('invalid acceptance identity')
    _default_only(facts)
    allowed = {'admission_policy','route','operational_budget','runtime_root','pinned_hermes_root',
               'weixin_base_url','timezone','preferences','support_contact'}
    if type(facts) is not dict or set(facts) != allowed or facts['support_contact'] is not None:
        raise ValueError('invalid fixed default raw facts')
    from .admission import AdmissionPolicy
    from .model_contract import FirstHopRoute, NonDiagnosticOperationalBudget
    policy = AdmissionPolicy(**facts['admission_policy'])
    route = FirstHopRoute.from_wire(facts['route'])
    budget = NonDiagnosticOperationalBudget.from_wire(facts['operational_budget'])
    if budget.route != route:
        raise ValueError('route and budget differ')
    manifest = _release(release_root)
    _runtime(facts['runtime_root'], release_root)
    # Only after complete pre-write target/content validation do we create the
    # private setup file and its narrowly scoped technical permits.
    _safe_directory(_HOME)
    previous = _read_private(_BINDING) if _BINDING.exists() else None
    if previous is not None: _default_only(previous)
    installation = (previous['core_binding']['installation_id'] if previous else 'installation:default:' + uuid.uuid4().hex)
    identity = {'installation_id': installation, 'site': 'site:default-dmit'}
    from .default_runtime import build_default_plan
    plan = build_default_plan(Path(release_root), copy.deepcopy(facts), identity)
    if type(plan) is not dict or not {'core_binding','head_binding','live_binding','gateway_config','roles','program_resources'} <= set(plan):
        raise ValueError('fixed default plan is incomplete')
    expires = (_now() + timedelta(hours=4)).isoformat()
    context = {'contract':'ticket119-run-context-v1', 'run_id':run_id,
               'executed_at_utc':_now().isoformat(), 'environment_class':'target-local-default',
               'target_ref':'target:default-hermes', 'run_scope':run_scope,
               'distribution_digest':manifest['release_digest'], 'approval_refs':{}, 'existing_report':None}
    _safe_directory(_PERMITS, create=True)
    for gate in sorted(_approval_gates(context)):
        permit = {'contract':'ticket128-gate-permit-v1','release_digest':manifest['host_release_digest'],
                  'distribution_digest':manifest['release_digest'],'run_id':run_id,'run_scope':run_scope,
                  'gate_id':gate,'target':_TARGET,'expires_at':expires,
                  'authorization_source':'owner-engineering-instruction:ticket128'}
        reference = _digest(permit)
        path = _PERMITS / (reference[7:]+'.json')
        if not path.exists(): _write_private(path, permit, exclusive=True)
        elif _read_private(path) != permit: raise ValueError('permit content drift')
        context['approval_refs'][gate] = reference
    plan.update(contract='ticket128-default-deployment-binding-v1',target=copy.deepcopy(_TARGET),
                release_root=str(Path(release_root).resolve()),release_digest=manifest['host_release_digest'],
                distribution_digest=manifest['release_digest'],run_context=context,
                execution_artifacts_root=str(_ARTIFACTS),facts=copy.deepcopy(facts))
    plan['gateway_config']['technical_acceptance'] = {'root':str(_ARTIFACTS),'identity':{
        'release_digest':manifest['host_release_digest'],'distribution_digest':manifest['release_digest'],
        'run_id':run_id,'run_scope':run_scope,'target':'default'}}
    _write_private(_BINDING,plan)
    return {'contract':'ticket128-default-prepare-result-v1','run_context':context,
            'execution_artifacts_root':str(_ARTIFACTS),'program_resources':plan['program_resources'],
            'roles':plan['roles']}


def _service(action, unit):
    if unit not in {'hermes-gateway.service','cohermes-default-core.service','cohermes-default-ordinary.service'}:
        raise ValueError('non-default service forbidden')
    environment = dict(os.environ)
    environment.setdefault('XDG_RUNTIME_DIR','/run/user/0')
    environment.setdefault('DBUS_SESSION_BUS_ADDRESS','unix:path=/run/user/0/bus')
    return subprocess.run(['systemctl','--user',action,unit],env=environment,
                          capture_output=True,text=True,timeout=60).returncode == 0


def _reload():
    return subprocess.run(['systemctl','--user','daemon-reload'],capture_output=True,text=True,timeout=60).returncode == 0


def _rpc(plan,kind,name,payload=None):
    selector = 'projection' if kind == 'managed-read' else 'operation'
    request = {'protocol_version':1,'kind':kind,'request_id':'acceptance:'+uuid.uuid4().hex,
               'payload':{'interface':'health-entry-v1',selector:name,'payload':payload or {}}}
    body = _bytes(request)
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(5);client.connect(plan['core_binding']['socket_path'])
        client.sendall(struct.pack('>I',len(body))+body); client.shutdown(socket.SHUT_WR)
        def exact(size):
            output=b''
            while len(output)<size:
                part=client.recv(size-len(output))
                if not part: raise ValueError('CorePort unavailable')
                output+=part
            return output
        size=struct.unpack('>I',exact(4))[0]
        if size>65536: raise ValueError('CorePort reply bound')
        reply=_strict_json_bytes(exact(size))
    if reply.get('status') != 'accepted': raise ValueError('CorePort denied')
    return reply['payload']


def _program_paths(plan):
    result=[]
    protected=Path('/var/lib/cohermes-default-core')
    for value in plan['program_resources']:
        path=Path(value)
        if (not path.is_absolute() or path == _HOME or path == Path('/root')
                or path.is_relative_to(protected) or protected.is_relative_to(path)
                or path.is_relative_to(_ARTIFACTS) or path.is_relative_to(_PERMITS)):
            raise ValueError('unsafe program rollback resource')
        if any(path == p or path.is_relative_to(p) or p.is_relative_to(path) for p in result):
            raise ValueError('overlapping program rollback resources')
        result.append(path)
    if len(result)<5: raise ValueError('incomplete program rollback boundary')
    return result


def _snapshot(plan,key):
    backup=_HOME/'.ticket128-program-backups'/key.split(':')[-1]
    _safe_directory(backup,create=True)
    metadata=[]
    for index,path in enumerate(_program_paths(plan)):
        entry={'path':str(path),'exists':path.exists() or path.is_symlink(),'slot':str(index)}
        if entry['exists']:
            details=path.lstat()
            entry.update(uid=details.st_uid,gid=details.st_gid,mode=stat.S_IMODE(details.st_mode))
            destination=backup/str(index)
            if path.is_symlink():
                entry['kind']='symlink';entry['link']=os.readlink(path)
            elif path.is_dir():
                entry['kind']='directory';shutil.copytree(path,destination,symlinks=True)
                entry['tree_metadata']=[{'path':str(item.relative_to(path)), 'uid':item.lstat().st_uid,
                    'gid':item.lstat().st_gid,'mode':stat.S_IMODE(item.lstat().st_mode)} for item in path.rglob('*')]
            elif path.is_file():
                entry['kind']='file';shutil.copy2(path,destination)
            else: raise ValueError('unsupported program resource')
        metadata.append(entry)
    enabled={role['unit']:subprocess.run(['systemctl','--user','is-enabled',role['unit']],
        capture_output=True,text=True,timeout=30).stdout.strip() for role in plan['roles']}
    body={'contract':'ticket128-program-backup-v1','release_digest':plan['release_digest'],
          'distribution_digest':plan['distribution_digest'],'execution_key':key,
          'resources':metadata,'enabled':enabled,'safe_isolated_baseline':_safe_baseline(plan),
          'authority_namespace_absent':not Path('/var/lib/cohermes-default-core').exists()}
    _write_private(backup/'backup.json',body,exclusive=True)
    return backup,body


def _isolation_bytes(plan):
    paths=[Path(role['unit_path']) for role in plan['roles']]
    paths += [Path(str(path)+'.d') for path in list(paths)]
    paths += [_HOME/'config.yaml',_HOME/'.ticket128-gateway.json',_HOME/'plugins/health-weixin']
    result={}
    for path in paths:
        if path.is_symlink():raise ValueError('unsafe isolation resource')
        if not path.exists():result[str(path)]=None
        elif path.is_file():result[str(path)]='sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()
        elif path.is_dir():
            items=[]
            for item in sorted(path.rglob('*')):
                if item.is_symlink():raise ValueError('unsafe isolation resource')
                if item.is_file():items.append([str(item.relative_to(path)),hashlib.sha256(item.read_bytes()).hexdigest()])
            result[str(path)]=_digest({'files':items})
    return result


def _live_role_identity(plan):
    for role in plan['roles']:
        completed=subprocess.run(['systemctl','--user','show',role['unit'],'--property=MainPID','--value'],capture_output=True,text=True,timeout=15)
        pid=int(completed.stdout.strip())
        fields={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in Path('/proc/'+str(pid)+'/status').read_text().splitlines() if ':' in line}
        if (int(fields['Uid'].split()[1])!=role['uid'] or int(fields['Gid'].split()[1])!=role['gid']
                or fields.get('NoNewPrivs')!='1' or any(int(fields[name],16)!=0 for name in ('CapInh','CapPrm','CapEff','CapBnd','CapAmb'))):
            return False
    return True


def _safe_baseline(plan):
    # Only an actual prior successful G10 observation can establish a safe
    # isolation baseline. Unit text or an operator's Boolean is insufficient.
    try:
        current=_isolation_bytes(plan)
        for path in _ARTIFACTS.glob('*.installation.json'):
            proof=_read_private(path)
            gate_path=path.with_name(path.name.replace('.installation.json','.gate.json'))
            if not gate_path.exists():continue
            gate=_read_private(gate_path)
            if (gate['observation']['result']=='passed' and gate['request']['gate_id']=='119-G10'
                    and proof.get('execution_key')==gate['request']['execution_key']
                    and proof.get('isolation_bytes')==current):return True
        return False
    except (OSError,ValueError,KeyError):return False


def _restore(plan,backup,body):
    for role in reversed(plan['roles']):_service('stop',role['unit'])
    clean_genesis=body.get('authority_namespace_absent') is True and _fresh_genesis(plan)
    if clean_genesis:
        for path in (Path('/var/lib/cohermes-default-core'),Path('/run/cohermes-default')):
            if path.is_symlink():return False
            if path.exists():shutil.rmtree(path)
    for entry in body['resources']:
        path=Path(entry['path'])
        if path.is_symlink() or path.is_file():path.unlink()
        elif path.exists():shutil.rmtree(path)
        if not entry['exists']:continue
        path.parent.mkdir(parents=True,exist_ok=True)
        if entry['kind']=='directory':shutil.copytree(backup/entry['slot'],path,symlinks=True)
        elif entry['kind']=='file':shutil.copy2(backup/entry['slot'],path)
        else:path.symlink_to(entry['link'])
        if not path.is_symlink():
            os.chown(path,entry['uid'],entry['gid']);os.chmod(path,entry['mode'])
            for details in entry.get('tree_metadata',[]):
                item=path/details['path'];os.chown(item,details['uid'],details['gid'],follow_symlinks=False)
                if not item.is_symlink():os.chmod(item,details['mode'])
    _reload()
    for unit,state in body['enabled'].items():
        if state in {'enabled','enabled-runtime'}:_service('enable',unit)
        elif state in {'disabled','not-found',''}:_service('disable',unit)
    # Health authority remains intact. Once any health state exists, an unsafe
    # root Agent baseline may never be restarted by program rollback.
    if not body['safe_isolated_baseline'] and not clean_genesis:
        return False
    roles=plan['roles'] if body['safe_isolated_baseline'] else [r for r in plan['roles'] if r['role']=='gateway' and Path(r['unit_path']).is_file()]
    if not roles:return False
    for role in roles:
        if not _service('start',role['unit']):return False
    return all(_service('is-active',role['unit']) for role in roles)


def _permit(plan,request):
    ref=request['approval_ref']
    if type(ref) is not str or not _DIGEST.fullmatch(ref):raise PermissionError('gate approval unavailable')
    body=_read_private(_PERMITS/(ref[7:]+'.json'))
    expected={'contract':'ticket128-gate-permit-v1','release_digest':request['release_digest'],
              'distribution_digest':request['distribution_digest'],'run_id':request['run_id'],
              'run_scope':request['run_scope'],'gate_id':request['gate_id'],'target':_TARGET}
    if (set(body)!=set(expected)|{'expires_at','authorization_source'} or _digest(body)!=ref or any(body.get(k)!=v for k,v in expected.items())
            or _time(body['expires_at'])<=_now()):raise PermissionError('gate approval mismatch')
    return body


def _consume(request):
    path=_HOME/'.ticket120-consumed-permits'/request['approval_ref'][7:]/(request['execution_key']+'.json')
    _write_private(path,{'execution_key':request['execution_key'],'permit_digest':request['approval_ref'],
                         'release_digest':request['release_digest']},exclusive=True)


def _observation(request,result,*,evidence=(),rollback_status='available',effect=None,reason='verified'):
    source=Path(__file__).read_bytes()
    return {'contract':'ticket119-gate-observation-v1',
        **{k:request[k] for k in ('release_digest','distribution_digest','run_scope','run_id','gate_id','execution_key','environment_class')},
        'observed_at_utc':request['executed_at_utc'],'executor_digest':'sha256:'+hashlib.sha256(source).hexdigest(),
        'step_digest':_digest({'gate':request['gate_id'],'reason':reason}),
        'fixture_digest':_digest({'distribution_digest':request['distribution_digest'],'run_scope':request['run_scope']}),
        'result':result,'evidence_refs':list(evidence),'blocking_evidence_refs':[],
        'rollback_ref':'program-backup:'+request['execution_key'].split(':')[-1],
        'rollback_status':rollback_status,'impact_ref':'impact:'+reason,'next_step_ref':'next:continue' if result=='passed' else 'next:stop-same-execution',
        'acceptance_receipt_refs':None,'effect_stage_refs':effect}


class DefaultAcceptanceGateExecutor:
    """No-argument default target adapter returning the strict 119 plain wire."""
    def execute(self,request):
        if type(request) is not dict:
            raise ValueError('invalid gate request')
        expected={'contract','release_digest','distribution_digest','run_scope','run_id','gate_id','execution_key',
                  'environment_class','executed_at_utc','target_ref','approval_ref'}
        if set(request)!=expected or request['contract']!='ticket119-gate-request-v1':
            raise ValueError('explicit current distribution binding required')
        _safe_directory(_HOME)
        plan=_read_private(_BINDING)
        _default_only(plan)
        context=plan['run_context']
        if (request['gate_id'] not in _gates(context)
                or any(request[k]!=context[k] for k in ('run_id','run_scope','distribution_digest','target_ref'))
                or request['release_digest']!=plan['release_digest']
                or request['execution_key']!=_bound_execution_key(plan['release_digest'],context,request['gate_id'])):
            return _observation(request,'not-authorized',reason='binding-mismatch')
        manifest=_release(plan['release_root'])
        if (manifest['release_digest']!=request['distribution_digest']
                or manifest['host_release_digest']!=request['release_digest']):
            return _observation(request,'cannot-confirm',reason='content-drift')
        _safe_directory(_ARTIFACTS,create=True)
        key=request['execution_key'].split(':')[-1]
        receipt=_ARTIFACTS/(key+'.gate.json')
        if receipt.exists():
            value=_read_private(receipt)
            if value.get('request')==request:return copy.deepcopy(value['observation'])
            return _observation(request,'cannot-confirm',reason='immutable-gate-conflict')
        # Gate ordering is checked again at the real adapter. No caller can
        # install or send by calling this object directly with a future gate.
        prior=_gates(context)[:_gates(context).index(request['gate_id'])]
        for gate in prior:
            prior_key=_bound_execution_key(plan['release_digest'],context,gate).split(':')[-1]
            prior_receipt=_ARTIFACTS/(prior_key+'.gate.json')
            if not prior_receipt.exists() or _read_private(prior_receipt)['observation']['result']!='passed':
                return _observation(request,'not-authorized',reason='prerequisite-missing')
        try:
            approval=None
            if request['gate_id'] in _approval_gates(context):approval=_permit(plan,request)
            observation=self._execute(plan,request,manifest,approval)
        except PermissionError:
            observation=_observation(request,'not-authorized',reason='approval-unavailable')
        except Exception:
            observation=_observation(request,'cannot-confirm',reason='execution-unconfirmed')
        _write_private(receipt,{'request':request,'observation':observation},exclusive=True)
        return observation

    def _execute(self,plan,request,manifest,approval):
        gate=request['gate_id']
        if gate=='119-G10':return self._install(plan,request)
        if gate=='119-G11':return self._technical(plan,request,approval)
        if gate=='128-ND12':return self._technical(plan,request,approval)
        if gate=='119-G12' or gate=='119-G07':
            return _observation(request,'cannot-confirm',reason='medical-owner-evidence-required')
        if gate=='128-ND07':
            resource=_strict_json_bytes((Path(plan['release_root'])/'assets/non-diagnostic/runtime-resources.json').read_bytes())
            safety=resource['safety_diagnostic_assets']
            if (safety['diagnostic_scope_bundle'] is not None or resource['knowledge_releases']
                    or resource['editorial_review']['status']!='approved'):
                return _observation(request,'cannot-confirm',reason='nd-content-unavailable')
            return _observation(request,'passed',evidence=['nd-content:'+_digest(resource)[7:]])
        return self._local_gate(plan,request,manifest)

    def _local_gate(self,plan,request,manifest):
        return _run_local_gate(plan,request,manifest)

    def _technical(self,plan,request,approval):
        return _technical_gate(self,plan,request,approval)

    def _install(self,plan,request):
        backup,body=_snapshot(plan,request['execution_key'])
        _consume(request)
        try:
            from .default_runtime import provision_default_plan
            installed=provision_default_plan(plan)
            if type(installed) is not dict:raise ValueError('installation plan unavailable')
            plan.clear();plan.update(installed)
            _write_private(_BINDING,plan)
            if not _reload():raise ValueError('daemon reload failed')
            for role in plan['roles']:
                if not _service('restart',role['unit']):raise ValueError('service restart failed')
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                try:
                    probe=_rpc(plan,'managed-read','health-entry-initialization')
                    if all(_service('is-active',r['unit']) for r in plan['roles']):break
                except (ValueError,OSError):pass
                time.sleep(.1)
            else:raise ValueError('live startup unconfirmed')
            if not _live_role_identity(plan):raise ValueError('actual role identity unconfirmed')
            installation={'contract':'ticket128-installation-observation-v1','execution_key':request['execution_key'],
                'release_digest':request['release_digest'],'distribution_digest':request['distribution_digest'],
                'isolation_bytes':_isolation_bytes(plan)}
            _write_private(_ARTIFACTS/(request['execution_key'].split(':')[-1]+'.installation.json'),installation,exclusive=True)
            return _observation(request,'passed',evidence=['installation:'+_digest({'key':request['execution_key'],'probe':probe})[7:]])
        except Exception:
            restored=_restore(plan,backup,body)
            return _observation(request,'failed' if restored else 'cannot-confirm',
                                rollback_status='completed' if restored else 'cannot-confirm',reason='installation-failed')


# Fixed validation programs are sealed with the same runtime. No filename,
# import name or executable can be supplied by an operation binding.
_LOCAL_MODULES = {
    '119-G02': ('tests.test_ticket110_boundary','tests.test_ticket111_admission_initialization',
        'tests.test_ticket112_evidence_profile','tests.test_ticket112_portrait_revision_contract',
        'tests.test_ticket112_portrait_schema','tests.test_ticket112_seven_skill_daily_turn',
        'tests.test_ticket112_storage_migration','tests.test_ticket114_authority_integration',
        'tests.test_ticket114_contract','tests.test_ticket114_rights','tests.test_ticket114_settings_controls',
        'tests.test_ticket114_status','tests.test_ticket115_authority','tests.test_ticket115_delivery',
        'tests.test_ticket115_health_commands','tests.test_ticket115_integration','tests.test_ticket115_plugin_delivery',
        'tests.test_ticket115_review','tests.test_ticket115_storage','tests.test_ticket115_tasks',
        'tests.test_ticket116_integration','tests.test_ticket117_integration','tests.test_ticket130_governed_runtime'),
    '119-G03': ('tests.test_ticket121_host_authority',
        *('tests.test_ticket123_production_core_service.Ticket123ProductionCoreServiceTests.' + name for name in (
        'test_v123_01_composition_is_release_bound_and_staged_is_truthfully_unavailable',
        'test_v123_02_af_unix_acl_and_peer_credentials_are_both_enforced',
        'test_v123_03_all_three_coreport_kinds_use_one_strict_byte_stream',
        'test_v123_04_restart_and_authority_faults_do_not_create_a_second_result',
        'test_v123_05_filesystem_lifecycle_adapters_are_atomic_and_restartable',
        'test_v123_07_no_plaintext_or_ordinary_state_copy_is_created'))),
    '119-G04': ('tests.test_ticket113_authority_integration','tests.test_ticket115_integration',
        'tests.test_ticket122_dynamodb_current_head','tests.test_ticket129_host_current_head'),
    '119-G05': ('tests.test_ticket118_integration','tests.test_ticket124_live_entry'),
    '119-G06': ('tests.test_ticket113_contract','tests.test_ticket113_knowledge','tests.test_ticket113_nondiagnostic',
        'tests.test_ticket113_strict_port','tests.test_ticket125_partner_model','tests.test_ticket131_nondiagnostic_budget'),
    '119-G08': ('tests.test_ticket129_host_current_head',),
    '119-G09': ('tests.test_ticket126_live_delivery',),
}
_LOCAL_PROGRAM = r'''
import io,json,sys,unittest
from pathlib import Path
import partner_health_steward.production_core_service as production
assert Path(production.__file__).resolve().is_relative_to(Path(sys.executable).resolve().parent.parent)
root=Path(sys.argv[1]).resolve()
sys.path.insert(0,str(root))
import tests
assert Path(tests.__file__).resolve()==root/'tests/__init__.py'
sys.path.pop(0)
modules=json.loads(sys.argv[2])
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in modules)
output=io.StringIO()
result=unittest.TextTestRunner(stream=output,verbosity=0).run(suite)
print(json.dumps({'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
 'skips':len(result.skipped),'successful':result.wasSuccessful()},sort_keys=True))
raise SystemExit(0 if result.wasSuccessful() and result.testsRun>0 and not result.skipped else 1)
'''


def _run_local_gate(plan,request,manifest):
    runtime=Path(plan['facts']['runtime_root'])
    closure=_runtime(runtime,plan['release_root'])
    if request['gate_id']=='119-G01':
        resource=_strict_json_bytes((Path(plan['release_root'])/'assets/non-diagnostic/runtime-resources.json').read_bytes())
        if (resource['editorial_review']['status']!='approved' or len(resource['daily_skill_assets'])!=6
                or resource['safety_diagnostic_assets']['minimum_help_bundle'] is None):
            return _observation(request,'cannot-confirm',reason='release-incomplete')
        return _observation(request,'passed',evidence=['release-closure:'+manifest['release_digest'][7:],
            'runtime-closure:'+closure['closure_digest'][7:]])
    modules=_LOCAL_MODULES.get(request['gate_id'])
    if modules is None:return _observation(request,'cannot-confirm',reason='local-gate-unavailable')
    verifier=runtime/'acceptance-source'
    if not (verifier/'tests/__init__.py').is_file():
        return _observation(request,'cannot-confirm',reason='sealed-verifier-unavailable')
    environment={name:os.environ[name] for name in ('PATH','LANG','LC_ALL','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS') if name in os.environ}
    environment.update(PYTHONDONTWRITEBYTECODE='1',TICKET123_RUNTIME_ROOT=str(runtime),
        TICKET118_PINNED_HERMES_SOURCE=plan['facts']['pinned_hermes_root'])
    if request['gate_id']=='119-G08':_consume(request)
    completed=subprocess.run([str(runtime/'bin/python3'),'-I','-B','-c',_LOCAL_PROGRAM,str(verifier),json.dumps(modules)],
        env=environment,capture_output=True,text=True,timeout=540)
    try:result=json.loads(completed.stdout.strip())
    except (ValueError,TypeError):result={'successful':False,'tests':0,'errors':1,'failures':0,'skips':0}
    passed=(completed.returncode==0 and result.get('successful') is True and result.get('tests',0)>0
            and all(result.get(k)==0 for k in ('errors','failures','skips')))
    proof={'contract':'ticket128-fixed-local-validation-v1','release_digest':request['release_digest'],
        'distribution_digest':request['distribution_digest'],'execution_key':request['execution_key'],
        'command_version':'ticket128-fixed-local-validation-v1','modules':list(modules),
        'runtime_closure_digest':closure['closure_digest'],'exit_status':completed.returncode,'result':result}
    _write_private(_ARTIFACTS/(request['execution_key'].split(':')[-1]+'.local-proof.json'),proof,exclusive=True)
    return _observation(request,'passed' if passed else 'cannot-confirm',
        evidence=['local-proof:'+_digest(proof)[7:]],reason='verified' if passed else 'local-verification-failed')




_SEQUENCE_PROGRAM = r'''
import json,sys
from dataclasses import asdict
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from partner_health_steward.host_authority import HostPrivateFacilityPaths,HostPrivateKeyProvider
from partner_health_steward.host_current_head import HostHeadBinding,HostSQLiteCurrentHead
from partner_health_steward.storage import EncryptedStateStore
from partner_health_steward.initialization import stable_digest
from partner_health_steward.rights import ManagedExport
value=json.load(sys.stdin);binding=value['service']
head=HostSQLiteCurrentHead(HostHeadBinding(**value['head']['binding']))
keys=HostPrivateKeyProvider(HostPrivateFacilityPaths(**binding['host_private_paths']),binding['installation_id'])
store=EncryptedStateStore('file:'+binding['database_path']+'?mode=ro',keys)
try:
    authority=head.read().head
    current=store.finalized_authority()
    init=store.initialization();settings=store.owner_settings()
    valid=(current is not None and current==authority.as_authority() and not authority.terminal and store.verify_integrity(current))
    if not valid or init is None or init.phase!='enabled' or settings is None:
        print(json.dumps({'ready':False}));raise SystemExit(0)
    since=datetime.fromisoformat(value['since'])
    native=[r for r in store.native_cursor_receipts() if datetime.fromisoformat(r.envelope.received_at)>=since]
    sources={r.envelope.causal_id for r in native}
    receipts=[r for r in store.health_command_receipts() if r.result.get('source_causal_id',r.result.get('_source_causal_id')) in sources]
    actions={r.result.get('_governed_action') for r in receipts}
    effects=[store.model_effect_for_source(source,stage) for source in sources for stage in ('intake','answer')]
    unknown=any(e is not None and e.state=='unknown' for e in effects)
    reports=[getattr(e.payload,'model_report',None) for e in effects if e is not None]
    failed=any(r is not None and r.terminal_proven and r.candidate_digest is None and r.reason_code is not None for r in reports)
    answers=[store.model_effect_for_source(source,'answer') for source in sources]
    answered=any(e is not None and getattr(e.payload,'model_report',None) is not None and e.payload.model_report.candidate_digest is not None for e in answers)
    state=store.daily_state();tasks=store.task_runtime();reviews=store.daily_review_ledger()
    safety=[r.result for r in receipts if r.result.get('_ticket116_action')=='safety.evaluate']
    exports=[r for r in receipts if r.result.get('_governed_action')=='export-formed']
    outbox=store.delivery_outbox_state(settings.owner_id,settings.installation_id)
    exported=False
    for receipt in exports:
        metadata=receipt.result.get('details',{}); artifact=store.managed_export(metadata.get('artifact_ref'))
        if artifact is not None:
            ManagedExport.from_wire(artifact['export'])
            exported=exported or any(r.intent.business_fact_ref==receipt.causal_id and r.has_fact('accepted') and r.intent.payload_ref.startswith('live-governed-export:') for r in outbox.records)
    daily=[store.daily_turn(source) for source in sources]
    flags={'integrity':valid,'enabled':True,'route_current':settings.consent_enabled and settings.consent_path_status=='active' and settings.current_route_id==value['route']['route_id'] and settings.current_configuration_generation==value['route']['configuration_generation'],'record':bool(state.evidence_cards) and any(d is not None and d.phase=='finalized' for d in daily),
        'portrait':bool(state.portrait_topics),'answer':answered,'diagnostic_refusal':any(r.get('branch')=='out-of-scope' for r in safety),
        'known_failure':failed,'no_unknown':not unknown,'correction':bool(state.owner_correction_revisions) and 'correction-completed' in actions,
        'view':'/health-view' in actions,'export':exported,'help':'/health-help' in actions,
        'controls':{'/health-pause','/health-resume','/health-recording-stop','/health-recording-resume'}<=actions,
        'controls_readback':not settings.proactive_support_paused and not settings.recording_stopped,
        'cancelled_task':bool(settings.cancelled_task_refs) and 'task-cancelled' in actions,
        'due_task':tasks is not None and any(t.primary_label=='solved' for t in tasks.tasks) and 'task-due' in actions,
        'current_review':reviews is not None and datetime.now(ZoneInfo(settings.timezone)).date().isoformat() in {r.key.local_date for r in reviews.completed},
        'fixed_safety':any(r.get('branch')=='danger-escalation' for r in safety),
        'contact_unavailable':bool(safety) and all(r.get('contact_alert') is None for r in safety)}
    proof={'authority':asdict(authority),'flags':flags,'source_facts':sorted(sources),'receipt_digests':sorted(r.command_digest for r in receipts)}
    print(json.dumps({'ready':all(flags.values()),'checks':flags,'sequence_digest':stable_digest(proof)},sort_keys=True))
finally:
    store.close();keys.close();head.close()
'''


def _sequence(plan,since):
    role=next(r for r in plan['roles'] if r['role']=='core')
    data={'service':plan['core_binding'],'head':plan['head_binding'],'since':since,'route':plan['facts']['route']}
    environment={k:v for k,v in os.environ.items() if k in {'PATH','LANG','LC_ALL'}}
    completed=subprocess.run(['setpriv','--reuid',str(role['uid']),'--regid',str(role['gid']),'--clear-groups',
        str(Path(plan['core_binding']['runtime_root'])/'bin/python3'),'-I','-B','-c',_SEQUENCE_PROGRAM],
        input=_bytes(data).decode(),env=environment,capture_output=True,text=True,timeout=15)
    if completed.returncode!=0:return {'ready':False}
    result=json.loads(completed.stdout)
    if type(result) is not dict:return {'ready':False}
    return result


def _technical_gate(self,plan,request,approval):
    from .ticket128_technical import TechnicalAcceptanceChannel
    identity={'release_digest':request['release_digest'],'distribution_digest':request['distribution_digest'],
        'run_id':request['run_id'],'run_scope':request['run_scope'],'target':'default'}
    channel=TechnicalAcceptanceChannel(_ARTIFACTS,identity)
    _consume(request)
    deadline=time.monotonic()+300
    sequence_digest=None
    since=_now().isoformat()
    if request['gate_id']=='128-ND12':
        while time.monotonic()<deadline:
            facts=_sequence(plan,since)
            if facts.get('ready') is True:
                sequence_digest=facts['sequence_digest']
                _write_private(_ARTIFACTS/(request['execution_key'].split(':')[-1]+'.sequence.json'),
                    {'contract':'ticket128-nd-sequence-observation-v1','identity':identity,**facts},exclusive=True)
                break
            time.sleep(.5)
        else:return _observation(request,'cannot-confirm',reason='native-sequence-unconfirmed',effect={k:None for k in _STAGES})
    attempt=channel.begin(request['gate_id'],request['execution_key'],request['approval_ref'],approval['expires_at'],sequence_digest)
    channel.request_send(request['execution_key'])
    while time.monotonic()<deadline:
        try:
            attempt=channel.attempt(request['execution_key'])
            action=channel.action(request['execution_key'])
        except (OSError,ValueError):
            time.sleep(.1)
            continue
        model=attempt.get('model_result')
        if request['gate_id']=='119-G11' and model is not None and model.get('accepted') is not True:
            stages={k:None for k in _STAGES}
            stages['formed']='technical-formed:'+_digest({'formed':attempt['formed_at_utc']})[7:]
            stages['committed']='technical-committed:'+_digest({'key':request['execution_key'],'approval':request['approval_ref']})[7:]
            stages['attempted']=model.get('result_ref')
            if model.get('status')=='unknown':stages['unknown']='technical-unknown:'+_digest(model)[7:]
            return _observation(request,'cannot-confirm',reason='model-canary-unconfirmed',effect=stages)
        sent=attempt.get('send_result')
        if sent is not None and sent['status']!='accepted':
            return _observation(request,'cannot-confirm',reason='channel-canary-unconfirmed',effect={
                **{k:None for k in _STAGES},'attempted':sent['result_ref'],
                'unknown':sent['evidence_ref'] if sent['status']=='unknown' else None})
        if sent is not None and sent['status']=='accepted' and action is not None:
            if request['gate_id']=='128-ND12':
                current=_sequence(plan,since)
                if current.get('ready') is not True or current.get('sequence_digest')!=sequence_digest:
                    raise ValueError('sequence authority changed before acceptance')
            if (action['execution_key']!=request['execution_key'] or action['gate_id']!=request['gate_id']
                    or action['sequence_digest']!=sequence_digest):raise ValueError('technical action mismatch')
            stages={k:None for k in _STAGES}
            stages.update(formed='technical-formed:'+_digest({'formed':attempt['formed_at_utc']})[7:],
                committed='technical-committed:'+_digest({'key':request['execution_key'],'approval':request['approval_ref']})[7:],
                attempted='technical-attempt:'+_digest({'at':attempt['attempted_at_utc'],'key':request['execution_key']})[7:],
                interface_accepted=sent['result_ref'],delivered=action['delivered_ref'],read_or_action=action['read_or_action_ref'])
            return _observation(request,'passed',effect=stages,evidence=['technical-proof:'+_digest(action)[7:]])
        time.sleep(.1)
    stages={k:None for k in _STAGES}
    if attempt.get('send_result'):
        stages['interface_accepted']=attempt['send_result']['result_ref'] if attempt['send_result']['status']=='accepted' else None
    return _observation(request,'cannot-confirm',reason='native-action-unconfirmed',effect=stages)


_GENESIS_PROGRAM = r'''
import json,sys
from partner_health_steward.host_authority import HostPrivateFacilityPaths,HostPrivateKeyProvider
from partner_health_steward.host_current_head import HostHeadBinding,HostSQLiteCurrentHead
from partner_health_steward.storage import EncryptedStateStore
value=json.load(sys.stdin);binding=value['service']
head=HostSQLiteCurrentHead(HostHeadBinding(**value['head']['binding']))
keys=HostPrivateKeyProvider(HostPrivateFacilityPaths(**binding['host_private_paths']),binding['installation_id'])
store=EncryptedStateStore('file:'+binding['database_path']+'?mode=ro',keys)
try:
    current=head.read().head
    print(json.dumps({'fresh':current.generation==1 and not current.terminal and store.verify_integrity(current.as_authority())
        and store.initialization() is None and store.count_records()==0 and store.count_effects()==0
        and not store.native_cursor_receipts() and not store.health_command_receipts()}))
finally:store.close();keys.close();head.close()
'''


def _fresh_genesis(plan):
    # Failure to prove a completely unused namespace always preserves it.
    try:
        role=next(r for r in plan['roles'] if r['role']=='core')
        head=_strict_json_bytes(Path('/var/lib/cohermes-default-core/current-head.json').read_bytes())
        completed=subprocess.run(['setpriv','--reuid',str(role['uid']),'--regid',str(role['gid']),'--clear-groups',
            str(Path(plan['core_binding']['runtime_root'])/'bin/python3'),'-I','-B','-c',_GENESIS_PROGRAM],
            input=_bytes({'service':plan['core_binding'],'head':head}).decode(),
            env={'PATH':'/usr/bin:/bin'},capture_output=True,text=True,timeout=15)
        return completed.returncode==0 and json.loads(completed.stdout)=={'fresh':True}
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):return False
