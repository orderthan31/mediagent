"""Guarded per-job chunk cache: normalized receipts, never global input dedup."""
from video_service.execution_authorization import AuthorizationConflict
from video_service.workflow_tickets import digest
from video_service.storage import read_json
from .checkpoints import checkpoint_binding


class QueueAuthorization:
    def __init__(self,active,path,count,request_identity):
        self.active=active;self.path=path;self.count=count
        self.context=active['store'].execution(active['execution_id'])['context']
        self.slot=path.relative_to(active['store'].root).as_posix()
        self.binding=digest({'execution_input':checkpoint_binding(self.context),'slot':self.slot,'count':count,'request':request_identity})
        self.cached=active['store'].verified_chunks(self.slot,self.binding)
        if any(type(i) is not int or i<0 or i>=count for i in self.cached):raise AuthorizationConflict('chunk receipt 범위가 다릅니다.')
        if path.exists():
            saved=read_json(path)
            if saved.get('authorization_binding')!=self.binding or saved.get('count')!=count:
                raise AuthorizationConflict('과거 chunk 캐시의 승인/입력 binding을 검증할 수 없습니다. 추정 재사용/자동 전체 재호출하지 않습니다.')
            for index,value in saved['results'].items():
                if self.cached.get(int(index))!=value:raise AuthorizationConflict('chunk 캐시가 검증된 완료 receipt와 다릅니다.')

    def record(self,index,value):
        self.active['store'].chunk_receipt(self.active['execution_id'],self.slot,self.binding,index,value)
        self.cached[index]=value
