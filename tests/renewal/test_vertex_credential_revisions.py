"""Isolated SQL recorder: no PostgreSQL, cloud, credentials, or environment lookup."""
from contextlib import contextmanager
import json
import pytest
from test_vertex_contract_validation import account

from video_service.postgres.credentials import CredentialStore
from video_service.postgres.registry import Registry
from video_service.model_endpoints import canonical_hash

OWNER='a'*32
CONNECTION='b'*32

class Recorder:
    def __init__(self): self.calls=[]
    @contextmanager
    def connection(self): yield self
    def execute(self,sql,params):
        self.calls.append((sql,params)); return self
    def fetchone(self): return {'admin':True}

@pytest.fixture
def setup(monkeypatch):
    db=Recorder()
    parent={'revision':1,'state_revision':1}
    row=dict(name='Test',provider='vertex_ai',protocol='vertex_ai',endpoint='https://aiplatform.googleapis.com/v1/projects/test-project/locations/global/publishers/google',credential_ref=None,vertex_project='test-project',vertex_location='global')
    monkeypatch.setattr(Registry,'_connection',lambda *a,**k:(parent,row))
    monkeypatch.setattr(Registry,'_public_connection',lambda *a,**k:{'credential':'reference_set'})
    return db,row,CredentialStore(db,b'0'*32)

def test_encrypted_json_revisions_and_old_refs_preserved(setup,account):
    db,row,store=setup
    secret=json.dumps(account,indent=2)+' '*2000
    store.save(OWNER,CONNECTION,revision=1,secret=secret)
    sql,values=next(c for c in db.calls if c[0].startswith('INSERT INTO provider_credentials'))
    identity,encrypted=values[2:]
    assert secret.encode() not in encrypted
    aad=f'mideagent.provider.v1:{OWNER}:{CONNECTION}:{identity}'.encode()
    assert store._cipher.decrypt(encrypted[:12],encrypted[12:],aad).decode()==secret
    revision=next(c[1] for c in db.calls if c[0].startswith('INSERT INTO connection_revisions'))
    config={k:row[k] for k in ('name','provider','protocol','endpoint','vertex_project','vertex_location')}
    config['credential_ref']='db:'+identity
    assert revision[8]==canonical_hash(config)
    assert revision[9:]==('test-project','global')
    assert not any('revoked_at' in sql for sql,_ in db.calls)

@pytest.mark.parametrize('secret',['x'*4097,'line\nbreak','한글'])
def test_ordinary_limits_after_connection_lock(setup,secret):
    db,row,store=setup; row.update(provider='openai',protocol='openai')
    with pytest.raises(ValueError,match='^invalid_credential$'):
        store.save(OWNER,CONNECTION,revision=1,secret=secret)
    assert any('FOR UPDATE' in sql for sql,_ in db.calls)
    assert not any(sql.startswith('INSERT') for sql,_ in db.calls)

def test_ordinary_hash_unchanged_and_null_removal(setup):
    db,row,store=setup; row.update(provider='openai',protocol='openai')
    store.save(OWNER,CONNECTION,revision=1,secret=None)
    revision=next(c[1] for c in db.calls if c[0].startswith('INSERT INTO connection_revisions'))
    config={k:row[k] for k in ('name','provider','protocol','endpoint')};config['credential_ref']=None
    assert revision[8]==canonical_hash(config) and revision[9:]==(None,None)
    assert any('revoked_at' in sql for sql,_ in db.calls)
