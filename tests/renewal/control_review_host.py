"""Private-config child: real native calls and actual pre-SQL-ACK process death."""
import json,os,sys
from pathlib import Path
from video_service.agent_control import Target,_cli
from video_service.durable_control import SignalControl,DurableHost,BrokerReports
from video_service.postgres import Database
from video_service.postgres.remote_control import RemoteControl
from video_service.postgres.control_recovery import ControlRecovery
from video_service.control_ack_receipts import AckReceipts
assert os.environ.get('MIDEAGENT_CONTROL_DISPOSABLE')=='1'
config=json.loads(Path(sys.argv[1]).read_text());assert config['scope']=='isolated-admin-recovery'
group=config['group'];target=Target(config['target_id'],config['image_id'],tuple(tuple(p) for p in config['labels']))
class FaultReceipts(AckReceipts):
    def record(self,*args):
        super().record(*args)
        if config.get('fault')=='after_receipt':os._exit(23)
class FaultAdapter(SignalControl):
    def signal(self,*args):
        if config.get('fault')=='before_signal':os._exit(24)
        return super().signal(*args)
def runner(args):
    if args[:2] in (['container','start'],['container','kill']):
        with Path(config['call_log']).open('a') as log:log.write(json.dumps(args)+'\n');log.flush();os.fsync(log.fileno())
    return _cli(config['docker_context'],args)
store=RemoteControl(Database(config['dsn']));recovery=ControlRecovery(store)
host=DurableHost(store,FaultAdapter({group:(target,)},runner=runner),{group:[config['worker_id']]},BrokerReports(store.database,{group:('cpu',group)}),receipts=FaultReceipts(config['receipts'],Path(config['key_file']).read_bytes()),recovery=recovery)
try:host.step()
finally:host.close()
