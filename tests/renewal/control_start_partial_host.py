"""One isolated group, N pinned slots; actual post-ACK/pre-SQL process death."""
import json,os,sys
from pathlib import Path
from video_service.agent_control import Target,_cli
from video_service.durable_control import SignalControl,DurableHost,BrokerReports
from video_service.postgres import Database
from video_service.postgres.remote_control import RemoteControl
from video_service.postgres.control_recovery import ControlRecovery
from video_service.control_ack_receipts import AckReceipts
assert os.environ.get('MIDEAGENT_CONTROL_DISPOSABLE')=='1'
c=json.loads(Path(sys.argv[1]).read_text());assert c['scope']=='isolated-start-partial'
group=c['group'];targets=tuple(Target(t['target_id'],t['image_id'],tuple(tuple(v) for v in t['labels'])) for t in c['targets']);ids=[t['worker_id'] for t in c['targets']]
class FaultReceipts(AckReceipts):
    def record(self,action,*args):
        super().record(action,*args)
        if c.get('fault_action')==action['action']:os._exit(23)
def runner(args):
    if args[:2] in (['container','start'],['container','kill']):
        with Path(c['call_log']).open('a') as f:f.write(json.dumps(args)+'\n');f.flush();os.fsync(f.fileno())
    return _cli(c['docker_context'],args)
store=RemoteControl(Database(c['dsn']));host=DurableHost(store,SignalControl({group:targets},runner=runner),{group:ids},BrokerReports(store.database,{group:('cpu',group)}),receipts=FaultReceipts(c['receipts'],Path(c['key_file']).read_bytes()),recovery=ControlRecovery(store))
try:host.step()
finally:host.close()
