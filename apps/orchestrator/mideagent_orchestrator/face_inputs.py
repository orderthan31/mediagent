"""Read-only photo/target/settings preparation. No session, preview or job authority."""
from copy import deepcopy
import math
import re
from video_service.canonical import digest
from video_service.image_original import asset_media, verify_path, policy
from video_service.node_contracts import node_spec

ID = re.compile(r'[a-f0-9]{32}\Z')
SHA = re.compile(r'[a-f0-9]{64}\Z')
EXECUTION_REASONS = [
    '원본·대상 인물 선택이 아직 확인되지 않았습니다.',
    '같은 사진·영상·설정·실행기에 연결된 승인 미리보기가 없습니다.',
    '사진 입력을 얼굴 합성 실행으로 연결하는 절차가 아직 제공되지 않습니다.',
    '실행기의 실제 준비 상태는 확인하지 않았습니다.',
]


class FaceInputs:
    def __init__(self, runtime):
        self.runtime = runtime

    def _engine(self, db, sha=None):
        from video_service.postgres.engine_runtimes import EngineRuntimes
        try:
            return EngineRuntimes.resolve_in(db, 'faceswap', sha256=sha)
        except ValueError as exc:
            if str(exc) == 'engine_unavailable_or_pin_changed': return None
            raise

    def choices(self):
        with self.runtime.database.connection() as db:
            row = self._engine(db)
        return {'engines': [self.public_engine(row)] if row else [],
                'reason': '' if row else '사용 가능한 등록 얼굴 합성 실행기가 없습니다.',
                'options': deepcopy(node_spec('faceswap')['options']),
                'execution_ready': False, 'execution_reasons': list(EXECUTION_REASONS)}

    @staticmethod
    def public_engine(row):
        return {k: row[k] for k in ('role','revision','sha256')} | {'engine': row['descriptor']['engine']}

    def inspect(self, actor, selection):
        if (set(selection) != {'photo_asset_id','target_asset_id','engine_revision','engine_sha256','settings_revision','preset','video_codec'}
                or any(not isinstance(selection[k], str) or not ID.fullmatch(selection[k]) for k in ('photo_asset_id','target_asset_id'))
                or selection['settings_revision'] != 1 or type(selection['settings_revision']) is not int
                or any(selection[k] not in node_spec('faceswap')['options'][k] for k in ('preset','video_codec'))):
            raise ValueError('사진·영상과 지원하는 합성 설정을 선택하세요.')
        revision=selection['engine_revision'];sha=selection['engine_sha256']
        if (revision is None) != (sha is None) or revision is not None and (
                type(revision) is not int or revision < 1 or not isinstance(sha,str) or not SHA.fullmatch(sha)):
            raise ValueError('등록 실행기 버전을 다시 선택하세요.')
        def bind(db):
            photo=self.runtime._shared_asset(db,selection['photo_asset_id'])
            target=self.runtime._shared_asset(db,selection['target_asset_id'])
            media=asset_media(photo)
            if media is None: raise ValueError('검증된 JPEG·PNG 사진 원본을 선택하세요.')
            pref=self.runtime.asset_reference(photo);vref=self.runtime.asset_reference(target)
            video=target.get('metadata',{}).get('media') or {}
            if (vref['type']!='video' or vref['bytes']>256*1024**2
                    or type(video.get('duration')) not in (int,float) or not math.isfinite(video['duration'])
                    or not 0 < video['duration'] <= 30
                    or any(type(video.get(k)) is not int for k in ('width','height'))
                    or not 0 < video['width'] <= 1280 or not 0 < video['height'] <= 720):
                raise ValueError('대상은 검증된 30초·1280×720·256MiB 이내 영상이어야 합니다.')
            engine=self._engine(db,sha) if sha else None
            if sha and (engine is None or engine['revision']!=revision):
                raise ValueError('등록 실행기가 변경되었거나 사용할 수 없습니다. 다시 선택하세요.')
            def source(row,ref,media):
                return {'asset_id':row['id'],'custodian_id':row['owner_id'],'reference':ref,
                        'filename':row['filename'],'media':deepcopy(media)}
            return {'version':1,'kind':'faceswap_inputs_v1','actor':actor,'source_workflow':None,
                    'photo':source(photo,pref,media),'target':source(target,vref,video),
                    'photo_policy':policy(),'engine':deepcopy({k:engine[k] for k in ('role','revision','sha256','descriptor')}) if engine else None,
                    'settings':{'revision':1,**{k:selection[k] for k in ('preset','video_codec')}}}
        with self.runtime.database.connection() as db: frozen=bind(db)
        # Verified CAS I/O and CPU image decode outside DB/job/scheduling locks.
        photo=frozen['photo'];target=frozen['target']
        verify_path(self.runtime.store.path(photo['custodian_id'],photo['reference']),photo['media'],photo['reference']['bytes'])
        self.runtime.store.path(target['custodian_id'],target['reference'])
        with self.runtime.database.connection() as db:
            if bind(db)!=frozen: raise ValueError('원본·대상·실행기가 변경됐습니다. 입력을 다시 확인하세요.')
        return {'profile':'faceswap_inputs_v1','token':digest(frozen),'bindings':frozen,
                'input_ready':frozen['engine'] is not None,'execution_ready':False,
                'input_reasons':[] if frozen['engine'] else ['등록 얼굴 합성 실행기를 선택하세요.'],
                'execution_reasons':list(EXECUTION_REASONS)}

    @staticmethod
    def public(plan):
        return {k:v for k,v in plan.items() if k!='bindings'}
