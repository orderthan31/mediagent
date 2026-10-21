"""Signed host-private ACK receipts. API never receives the signing key.

Write only after a native lifecycle call returns success and before its DB ACK.
These facts do not themselves declare worker/job success or authorize a replay.
"""
import hashlib
import hmac
import json
import os
import re
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
from .agent_control import ControlError


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()


class AckReceipts:
    def __init__(self, root, key):
        self.root=Path(root)
        if not isinstance(key,bytes) or len(key)!=32 or self.root.is_symlink():raise ControlError('invalid_ack_receipt_store')
        self.root.mkdir(parents=True,exist_ok=True);self.key=key

    def _path(self, identity):
        if not isinstance(identity,str) or not re.fullmatch('[a-f0-9]{32}',identity):raise ControlError('invalid_ack_receipt_identity')
        path=self.root/(identity+'.json')
        if path.is_symlink():raise ControlError('invalid_ack_receipt_path')
        return path

    def _binding(self, action, contract, target):
        issued=action['issued_at'].isoformat() if isinstance(action['issued_at'],datetime) else action['issued_at']
        return {'version':1,'action_id':action['id'],'request_id':action['request_id'],'worker_id':action['worker_id'],
                'action':action['action'],'before_boot_id':action['before_boot_id'],'issued_at':issued,
                'contract_sha256':contract,'target_id':target.container_id,'image_id':target.image_id}

    def record(self, action, contract, target, after):
        path=self._path(action['id'])
        if path.exists():
            self.read(action,contract,target);return
        facts={**self._binding(action,contract,target),'native_return_code':0,
               'acknowledged_at':datetime.now(timezone.utc).isoformat(),'after_started_at':after['started_at']}
        document={'facts':facts,'signature':hmac.new(self.key,canonical(facts),hashlib.sha256).hexdigest()}
        temporary=self.root/('.'+uuid4().hex+'.tmp')
        try:
            with temporary.open('xb') as stream:stream.write(canonical(document));stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,path)
        except OSError:raise ControlError('ack_receipt_write_failed') from None
        finally:
            if temporary.exists():temporary.unlink()

    def read(self, action, contract, target):
        path=self._path(action['id'])
        if not path.exists():return None
        try:
            raw=path.read_bytes()
            if len(raw)>8192:raise ValueError
            value=json.loads(raw);facts=value['facts']
            if set(value)!={'facts','signature'} or set(facts)!=set(self._binding(action,contract,target))|{'native_return_code','acknowledged_at','after_started_at'}:raise ValueError
            if not hmac.compare_digest(value['signature'],hmac.new(self.key,canonical(facts),hashlib.sha256).hexdigest()):raise ValueError
            if any(facts.get(k)!=v for k,v in self._binding(action,contract,target).items()) or facts['native_return_code']!=0:raise ValueError
            return {'facts':facts,'sha256':hashlib.sha256(raw).hexdigest()}
        except (OSError,ValueError,TypeError,KeyError):raise ControlError('ack_receipt_invalid') from None
