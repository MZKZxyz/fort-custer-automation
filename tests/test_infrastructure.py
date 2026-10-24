"""Trust-boundary regression tests; actual container checks run in make rehearsal."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from infrastructure import ContainerQA, ContainerRuntime, specification, validate_inspection, source_files, source_modes, artifact_digest, tree_digest
from github_app_setup import token_request, jwt_claims, validate_token_response, InstallationTokenBroker
from host_watchdog import expired, tick

IMAGE='sha256:'+'a'*64
NAME='fc54-'+'b'*32


def inspection(role='coding'):
 uid={'coding':65532,'qa':65531,'controller':65530}[role]
 return {'Name':'/'+NAME,'Config':{'Image':IMAGE,'User':f'{uid}:{uid}',
  'WorkingDir':'/workspace','Entrypoint':['python3','-I','/opt/worker_entry.py'],
  'Cmd':None,'Env':['FC_ROLE='+role,'HOME=/tmp','PATH=/usr/bin'], 'Volumes':None},
  'Mounts':[], 'HostConfig':{'ReadonlyRootfs':True,'Privileged':False,
   'NetworkMode':'none','CgroupnsMode':'private','Runtime':'runsc','IpcMode':'none','CapDrop':['ALL'],
   'SecurityOpt':['no-new-privileges'],'PidsLimit':128,'Memory':2147483648,
   'MemorySwap':2147483648,'NanoCpus':1000000000,'LogConfig':{'Type':'none'},
   'Tmpfs':{'/workspace':f'rw,nosuid,nodev,size=256m,uid={uid},gid={uid},mode=0700',
            '/tmp':f'rw,noexec,nosuid,nodev,size=64m,uid={uid},gid={uid},mode=0700'},
   'Ulimits':[{'Name':'fsize','Soft':8388608,'Hard':8388608},{'Name':'nofile','Soft':256,'Hard':256}]}}


class InfrastructureTests(unittest.TestCase):
 def test_effective_configuration_and_roles(self):
  for role in ('coding','qa'):
   self.assertTrue(validate_inspection(inspection(role),role,IMAGE,NAME))
  self.assertNotEqual(specification('coding',IMAGE,NAME),specification('qa',IMAGE,NAME))

 def test_escape_surface_mutations_rejected(self):
  for key,value in [('Privileged',True),('Binds',['/var/run/docker.sock:/var/run/docker.sock']),
   ('NetworkMode','host'),('ReadonlyRootfs',False),('CapAdd',['SYS_ADMIN']),('Runtime','runc'),
   ('PidMode','host'),('CgroupnsMode','host'),('Memory',0),('MemorySwap',-1),('NanoCpus',0),('PidsLimit',-1),
   ('SecurityOpt',[]),('Devices',[{}]),('DeviceRequests',[{}]),('IpcMode','host'),
   ('Tmpfs',{}),('ExtraHosts',['metadata:169.254.169.254']),('PortBindings',{'80':[]})]:
   with self.subTest(key=key):
    d=inspection();d['HostConfig'][key]=value
    with self.assertRaises(ValueError):validate_inspection(d,'coding',IMAGE,NAME)

 def test_mounts_command_env_and_credentials_rejected(self):
  mutations=[('Mounts',[{'Source':'/state'}]),('Config',dict(inspection()['Config'],Cmd=['sh'])),
   ('Config',dict(inspection()['Config'],User='0')),
   ('Config',dict(inspection()['Config'],Env=['FC_ROLE=coding','HOME=/tmp','OPENAI_API_KEY=synthetic'])),
   ('Config',dict(inspection()['Config'],Env=['FC_ROLE=coding','HOME=/tmp','HTTPS_PROXY=http://proxy']))]
  for key,value in mutations:
   d=inspection();d[key]=value
   with self.assertRaises(ValueError):validate_inspection(d,'coding',IMAGE,NAME)

 def test_no_floating_images_runtime_or_name_injection(self):
  for role,image,name,runtime in [('coding','worker:latest',NAME,'runsc'),('coding',IMAGE,'--privileged','runsc'),('coding',IMAGE,NAME,'runc'),('unknown',IMAGE,NAME,'runsc')]:
   with self.assertRaises(ValueError):specification(role,image,name,runtime=runtime)
  for timeout in (0,2401):
   with self.assertRaises(ValueError):ContainerRuntime().run('coding',IMAGE,{},timeout=timeout)

 def test_qa_commands_are_immutable_policy(self):
  qa=ContainerQA(IMAGE)
  with self.assertRaises(ValueError):qa.run(Path('/tmp'),('sh','-c','echo approve'))
  with self.assertRaises(ValueError):ContainerQA(IMAGE,'fixture',synthetic=False)

 def test_qa_artifact_and_exact_commit_binding(self):
  class Fake:
   def run(self,role,image,request):
    self.request=request
    return dict(request,tests=[{'name':'unit','status':'passed','exit_code':0}])
  fake=Fake();qa=ContainerQA(IMAGE,runtime=fake)
  with tempfile.TemporaryDirectory() as d:
   Path(d,'calc.py').write_text('pass')
   result=qa.run_exact(Path(d).resolve(strict=True),('policy','fixture'),'a'*40,'b'*40)
  self.assertEqual(result['status'],'passed')
  self.assertEqual(fake.request['candidate'],'b'*40)
  self.assertEqual(result['artifact_sha256'],artifact_digest({'calc.py':'pass'},{'calc.py':0o644}))

 def test_stale_or_failed_qa_rejected(self):
  class Fake:
   def __init__(self,change):self.change=change
   def run(self,role,image,request):
    return dict(request,tests=[{'status':'passed','exit_code':0}],**self.change)
  with tempfile.TemporaryDirectory() as d:
   for change in ({'artifact':'forged'},{'candidate':'c'*40},{'policy':'injected'}):
    qa=ContainerQA(IMAGE,runtime=Fake(change))
    with self.assertRaises(ValueError):qa.run_exact(Path(d).resolve(strict=True),('policy','fixture'),'a'*40,'b'*40)
   class Failed:
    def run(self,role,image,request):return dict(request,tests=[{'status':'passed','exit_code':1}])
   self.assertEqual(ContainerQA(IMAGE,runtime=Failed()).run(Path(d).resolve(strict=True),('policy','fixture'))['status'],'failed')

 def test_export_preserves_crlf_and_executable_mode(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d,'script.sh');p.write_bytes(b'echo fixture\r\n');p.chmod(0o755)
   self.assertEqual(source_files(Path(d).resolve(strict=True)),{'script.sh':'echo fixture\r\n'})
   self.assertEqual(source_modes(Path(d).resolve(strict=True)),{'script.sh':0o755})

 def test_private_files_and_links_not_transported(self):
  with tempfile.TemporaryDirectory() as d:
   Path(d,'.env').write_text('synthetic')
   with self.assertRaises(ValueError):source_files(Path(d).resolve(strict=True))
   Path(d,'.env').unlink();Path(d,'link').symlink_to('/etc/passwd')
   with self.assertRaises(ValueError):source_files(Path(d).resolve(strict=True))

 def test_short_lived_scoped_app_contract(self):
  repo='MZKZxyz/fort-custer-server'
  req=token_request('reader',repo)
  self.assertEqual(req['permissions'],{'contents':'read','issues':'read'})
  self.assertEqual(token_request('publisher',repo)['permissions'],{'contents':'write','pull_requests':'write'})
  with self.assertRaises(ValueError):token_request('publisher','other/server')
  claims=jwt_claims('configured-client-id',1000)
  self.assertLessEqual(claims['exp']-claims['iat'],600)
  r=dict(token='synthetic-placeholder',expires_at=datetime.fromtimestamp(2000,timezone.utc).isoformat(),permissions=req['permissions'],repositories=[{'full_name':repo}])
  self.assertEqual(validate_token_response(r,'reader',repo,1000),'synthetic-placeholder')
  implicit=dict(r,permissions=dict(r['permissions'],metadata='read'))
  self.assertEqual(validate_token_response(implicit,'reader',repo,1000),'synthetic-placeholder')
  for change in ({'expires_at':datetime.fromtimestamp(5000,timezone.utc).isoformat()},
                 {'permissions':{'contents':'write'}},{'repositories':[{'full_name':'other/repo'}]}):
   with self.assertRaises(ValueError):validate_token_response(dict(r,**change),'reader',repo,1000)
  with self.assertRaises(RuntimeError):InstallationTokenBroker().mint()

 def test_rejected_policy_never_starts_and_cleanup_is_checked(self):
  import subprocess
  d=inspection();d['HostConfig']['Privileged']=True
  def daemon(*args,**kwargs):
   if args[0]=='inspect':return subprocess.CompletedProcess([],0,json.dumps([d]).encode(),b'')
   return subprocess.CompletedProcess([],0,b'',b'')
  with patch('infrastructure.uuid.uuid4') as identity, patch('infrastructure.subprocess.run') as create, patch('infrastructure.docker',side_effect=daemon) as api, patch('infrastructure.Supervisor.run') as start:
   identity.return_value.hex='b'*32
   with self.assertRaises(ValueError):ContainerRuntime().run('coding',IMAGE,{})
   start.assert_not_called()
   self.assertIn(('rm','--force',NAME),[c.args for c in api.call_args_list])

 def test_asset_manifest_rejects_omission_tamper_and_link(self):
  sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'infra'))
  from verify_assets import verify
  import hashlib
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve(strict=True)
   for folder in ('npm-cache','mongodb','browsers'):(root/folder).mkdir()
   asset=root/'mongodb/mongod';asset.write_text('synthetic')
   manifest={'mongodb/mongod':hashlib.sha256(asset.read_bytes()).hexdigest()}
   (root/'manifest.json').write_text(json.dumps(manifest))
   self.assertEqual(set(verify(root)),set(manifest))
   asset.write_text('tampered')
   with self.assertRaises(ValueError):verify(root)
   asset.write_text('synthetic');(root/'extra').write_text('unlisted')
   with self.assertRaises(ValueError):verify(root)
   (root/'extra').unlink();(root/'link').symlink_to(asset)
   with self.assertRaises(ValueError):verify(root)

 def test_watchdog_uses_original_nonrenewable_start(self):
  stamp=datetime.fromtimestamp(1000,timezone.utc).isoformat()
  c={'State':{'StartedAt':stamp},'Created':stamp}
  self.assertFalse(expired(c,3399));self.assertTrue(expired(c,3400))
  c['Heartbeat']=3399
  self.assertTrue(expired(c,3400))
  self.assertTrue(expired(c,900))

 def test_watchdog_kills_on_bad_clock(self):
  import subprocess
  def daemon(*args,**kwargs):
   if args[0]=='ps':return subprocess.CompletedProcess([],0,b'container\n',b'')
   if args[0]=='inspect':return subprocess.CompletedProcess([],0,json.dumps([{'State':{'StartedAt':'bad'}}]).encode(),b'')
   self.assertEqual(args,('rm','--force','container'))
   return subprocess.CompletedProcess([],0,b'',b'')
  with patch('host_watchdog.docker',side_effect=daemon) as m:
   self.assertEqual(tick(1000),1);self.assertEqual(m.call_count,3)

if __name__=='__main__':unittest.main()
