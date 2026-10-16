import hashlib
import json
import logging

from video_service.storage import read_json, write_json_atomic


class Checkpoints:
    def __init__(self, work, identity, before_write):
        self.work = work
        self.identity = identity
        self.before_write = before_write

    def run(self, name, operation, files=()):
        from video_service.execution_authorization import active_authorization
        active=active_authorization()
        if active is not None:return self._guarded_run(active,name,operation,files)
        key = hashlib.sha256(json.dumps([self.identity, name], sort_keys=True).encode()).hexdigest()
        path = self.work / "checkpoints" / (key + ".json")
        try:
            saved = read_json(path)
            if all((self.work / name).is_file() and
                    [(self.work / name).stat().st_size, (self.work / name).stat().st_mtime_ns] == stamp
                    for name, stamp in saved["files"].items()) and set(saved["files"]) == set(files):
                logging.info("Resuming completed checkpoint: %s", name)
                return saved["result"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        result = operation()
        stamps = {name: [(self.work / name).stat().st_size, (self.work / name).stat().st_mtime_ns]
            for name in files}
        write_json_atomic(path, {"result": result, "files": stamps}, before_write=self.before_write)
        return result

    def _guarded_run(self,active,name,operation,files):
        from video_service.execution_authorization import AuthorizationConflict
        from video_service.workflow_tickets import digest
        from video_service.graph_tickets import file_sha
        from video_service.storage import resolve_under
        context=active['store'].execution(active['execution_id'])['context']
        binding=checkpoint_binding(context)
        key=digest({'contract':'wf08','identity':self.identity,'binding':binding,'name':name})
        path=self.work/'checkpoints'/(key+'.json')
        if path.is_file():
            saved=read_json(path)
            receipt=active['store'].execution(saved['authorization_execution']).get('checkpoint_receipts',{}).get(path.relative_to(active['store'].root).as_posix())
            if receipt!={'sha256':file_sha(path),'binding':binding,'name':name} or saved['binding']!=binding or set(saved['file_hashes'])!=set(files):
                raise AuthorizationConflict('완료 checkpoint receipt/입력 binding이 다릅니다. 자동 전체 재실행하지 않습니다.')
            for relative,sha in saved['file_hashes'].items():
                if file_sha(resolve_under(self.work.parent,self.work.name+'/'+relative))!=sha:raise AuthorizationConflict('완료 checkpoint 파일 bytes가 변경되었습니다. 재사용/자동 재호출하지 않습니다.')
            return saved['result']
        result=operation()
        hashes={relative:file_sha(resolve_under(self.work.parent,self.work.name+'/'+relative)) for relative in files}
        write_json_atomic(path,{'result':result,'file_hashes':hashes,'binding':binding,'name':name,'authorization_execution':active['execution_id']},before_write=self.before_write)
        active['store'].checkpoint_receipt(active['execution_id'],path.relative_to(active['store'].root).as_posix(),file_sha(path),binding,name)
        return result


def checkpoint_binding(context):
    from video_service.workflow_tickets import digest
    from video_service.models import JobOptions
    options=JobOptions.from_dict(context.get('options',{})).to_dict()
    serving={k:v for k,v in context.get('settings',{}).items() if k!='revision' and 'fallback' not in k}
    return digest({'contract':1,'source':context['inputs']['source']['sha256'],'options':options,'serving':serving,'environment':context.get('execution_environment',{})})
