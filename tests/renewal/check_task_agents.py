"""Goal-owned agents exercise real LangGraph/state and bound subtools; no provider I/O."""
import hashlib,json,pathlib,tempfile,unittest,uuid,wave
from video_service.cpu_agents import canonical

class TaskAgentTest(unittest.TestCase):
    def test_transcription_goal_reuses_audio_and_chunks_through_actual_subtools(self):
        from mideagent_models.transcription import TranscriptionAgent
        with tempfile.TemporaryDirectory() as folder:
            root=pathlib.Path(folder);audio=root/'audio.wav'
            with wave.open(str(audio),'wb')as f:
                f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\0\0'*32000)
            raw=audio.read_bytes()
            task={'version':1,'task_id':uuid.uuid4().hex,'role':'transcription','audio':{'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)},'model':{'model_id':uuid.uuid4().hex,'revision':1},'source_language':'en','chunk_frames':16000,'max_calls':2,'timeline':[{'packed_start':0,'packed_end':1,'source_start':10,'source_end':11},{'packed_start':1,'packed_end':2,'source_start':20,'source_end':21}]}
            calls=[]
            def model(*args):
                calls.append(1)
                return [{'start':0.1,'end':0.4,'text':'controlled speech'}]
            agent=TranscriptionAgent(root/'state',model)
            result=agent.run(task,audio)
            self.assertEqual(result['status'],'completed')
            self.assertEqual([round(r['start'],1)for r in result['segments']],[10.1,20.1])
            with agent.state.connect()as db:
                table=db.execute("SELECT name FROM sqlite_master WHERE name='agent_tool_steps'").fetchone()
                self.assertIsNotNone(table,'transcription goal only wraps one model call, not its subtools')
                tools={r[0]for r in db.execute('SELECT tool_id FROM agent_tool_steps WHERE task=?',(task['task_id'],))}
            self.assertEqual(tools,{'speech.prepare_audio','speech.transcribe','speech.validate_chunk','speech.merge_segments'})
            self.assertEqual(agent.registration['id'],'transcribe')
            before={p.name:(p.stat().st_mtime_ns,p.read_bytes())for p in (agent.root/task['task_id']).glob('*.wav')}
            self.assertEqual(agent.run(task,audio),result)
            self.assertEqual({p.name:(p.stat().st_mtime_ns,p.read_bytes())for p in (agent.root/task['task_id']).glob('*.wav')},before)
            self.assertEqual(len(calls),2)
            self.assertEqual(audio.read_bytes(),raw)

    def test_translation_goal_uses_subtools_and_keeps_source_identity(self):
        from mideagent_models.translation import TranslationAgent
        with tempfile.TemporaryDirectory() as folder:
            root=pathlib.Path(folder)
            rows=[{'id':f'cue-{i}','start':float(i*2),'end':float(i*2+1),'text':f'line {i}'}for i in range(205)]
            raw=canonical(rows);path=root/'source.json';path.write_bytes(raw)
            task={'version':1,'role':'translation','task_id':uuid.uuid4().hex,'transcript':{'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)},'models':[{'model_id':uuid.uuid4().hex,'revision':1}],'source_language':'en','target_language':'ko','batch_policy':'bounded_100x16k_v1','max_calls':4}
            calls=[]
            def model(frozen,batch,candidate):
                calls.append(batch.chunk_index)
                return {'status':'received','reply':json.dumps(['KO '+r['text']for r in batch.segments])}
            agent=TranslationAgent(root/'state',model)
            result=agent.run(task,path)
            self.assertEqual(result['status'],'completed')
            self.assertEqual(calls,[0,1,2])
            self.assertEqual([{k:v for k,v in r.items()if k!='text'}for r in result['segments']],[{k:v for k,v in r.items()if k!='text'}for r in rows])
            with agent.state.connect()as db:
                table=db.execute("SELECT name FROM sqlite_master WHERE name='agent_tool_steps'").fetchone()
                self.assertIsNotNone(table,'goal agent has no actual preparation/validation/assembly tool execution')
                tools={r[0]for r in db.execute('SELECT tool_id FROM agent_tool_steps WHERE task=?',(task['task_id'],))}
            self.assertEqual(tools,{'text.prepare_batches','text.translate','text.validate_batch','text.merge_batches'})
            self.assertEqual(agent.registration['id'],'translate')
            self.assertEqual(set(agent.registration['allowed_tools']),tools)
            self.assertFalse(agent.registration['model_driven_selection'])
            self.assertEqual(agent.run(task,path),result)
            self.assertEqual(calls,[0,1,2])

if __name__=='__main__':unittest.main()
