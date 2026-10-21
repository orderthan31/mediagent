"""Host-only durable ACK evidence, separate from the product API and DB phase."""
import importlib.util
import json
import secrets
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from video_service.agent_control import Target,ControlError


def test_native_ack_file_binds_request_target_boot_and_original_issue(tmp_path):
    assert importlib.util.find_spec('video_service.control_ack_receipts'),'durable native ACK evidence missing'
    from video_service.control_ack_receipts import AckReceipts
    receipts=AckReceipts(tmp_path,secrets.token_bytes(32))
    action={'id':uuid4().hex,'request_id':uuid4().hex,'worker_id':uuid4().hex,'action':'stop','before_boot_id':uuid4().hex,'issued_at':datetime.now(timezone.utc)}
    target=Target('a'*64,'sha256:'+'b'*64,(('com.docker.compose.project','fixture'),('com.docker.compose.service','encode')))
    assert receipts.read(action,'c'*64,target) is None
    receipts.record(action,'c'*64,target,{'started_at':'2026-01-01T00:00:00Z'})
    proof=receipts.read(action,'c'*64,target)
    assert proof['facts']['request_id']==action['request_id']
    assert proof['facts']['before_boot_id']==action['before_boot_id']
    assert proof['facts']['native_return_code']==0
    assert len(proof['sha256'])==64
    with pytest.raises(ControlError):receipts.read({**action,'request_id':uuid4().hex},'c'*64,target)
    path=tmp_path/(action['id']+'.json');tampered=json.loads(path.read_text());tampered['facts']['target_id']='d'*64;path.write_text(json.dumps(tampered))
    with pytest.raises(ControlError):receipts.read(action,'c'*64,target)
