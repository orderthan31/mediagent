"""Task-bound console tee. No Docker/DB authority and no invented lifecycle records."""
import contextlib,contextvars,datetime,io,json,os,re,sys,threading
from pathlib import Path
_context=contextvars.ContextVar('task_console',default=None)
_lock=threading.RLock()
_LIMIT=2*1024*1024

def redact(text,secrets=()):
 for secret in secrets:
  if secret:text=text.replace(secret,'[REDACTED]')
 text=re.sub(r'(?im)(?:authorization|proxy-authorization|set-cookie|cookie|password|api[-_]?key|access[-_]?token|refresh[-_]?token|credential|secret)\s*[:=].*$', '[REDACTED authentication data]',text)
 text=re.sub(r'(?i)\b(?:Bearer|Basic)\s+[^\s,;]+','[REDACTED authentication data]',text)
 text=re.sub(r'https?://[^\s\"\x27]+',lambda m:m[0].split('?')[0].split('#')[0]+'?[REDACTED]'if'?'in m[0]or'#'in m[0]else re.sub(r'//[^/@]+:[^/@]+@','//[REDACTED]@',m[0]),text)
 text=re.sub(r'\b(?:sk-|AIza)[A-Za-z0-9_-]{12,}','[REDACTED]',text)
 text=re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+','[REDACTED]',text)
 return text

def _identity(value):
 if not isinstance(value,str)or not re.fullmatch('[a-f0-9]{32}',value):raise ValueError('invalid_task_identity')
 return value

class _Stream:
 def __init__(self,target,kind):self.target=target;self.kind=kind
 def __getattr__(self,name):return getattr(self.target,name)
 def write(self,text):
  context=_context.get()
  if context is None:return self.target.write(text)
  buffer=context['pending'].get(self.kind,'')+text
  lines=buffer.split('\n');context['pending'][self.kind]=lines.pop()
  for line in lines:self.record(context,line)
  if len(context['pending'][self.kind])>8192:
   self.record(context,context['pending'][self.kind][:8192]);context['pending'][self.kind]=''
  return len(text)
 def record(self,context,line):
  row={'task_id':context['task'],'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'stream':self.kind,'text':redact(line,context['secrets'])[:8192]}
  encoded=json.dumps(row,ensure_ascii=False)+'\n'
  with _lock:
   self.target.write(encoded);self.target.flush()
   if context['root']:
    try:
     folder=Path(context['root']);folder.mkdir(parents=True,exist_ok=True);path=folder/(context['task']+'.jsonl')
     if path.is_symlink():return
     if not path.exists()or path.stat().st_size<_LIMIT:
      with path.open('a',encoding='utf8',newline='')as f:f.write(encoded)
    except OSError:pass # native console still contains the record; never rerun model work
 def flush(self):self.target.flush()

def install_capture():
 with _lock:
  if not isinstance(sys.stdout,_Stream):sys.stdout=_Stream(sys.stdout,'stdout')
  if not isinstance(sys.stderr,_Stream):sys.stderr=_Stream(sys.stderr,'stderr')

@contextlib.contextmanager
def capture_console(task_id,*,root=None,secrets=()):
 _identity(task_id);install_capture()
 value={'task':task_id,'root':root or os.environ.get('MIDEAGENT_TASK_CONSOLE_ROOT'),'secrets':secrets,'pending':{}}
 token=_context.set(value)
 try:yield
 finally:
  for kind,stream in [('stdout',sys.stdout),('stderr',sys.stderr)]:
   if value['pending'].get(kind)and isinstance(stream,_Stream):stream.record(value,value['pending'][kind])
  _context.reset(token)

def read_console(task_id,*,root=None):
 _identity(task_id);folder=root or os.environ.get('MIDEAGENT_TASK_CONSOLE_ROOT');lines=[]
 if not folder:return {'lines':lines,'available':False,'truncated':False}
 path=Path(folder)/(task_id+'.jsonl')
 if path.is_symlink():raise ValueError('console_symlink_rejected')
 try:
  with path.open('rb')as f:raw=f.read(_LIMIT)
 except FileNotFoundError:return {'lines':lines,'available':False,'truncated':False}
 for item in raw.decode('utf8',errors='replace').splitlines():
  try:row=json.loads(item)
  except ValueError:continue # a concurrently appended partial line is read next time
  if row.get('task_id')!=task_id or row.get('stream')not in {'stdout','stderr'}:continue
  if not isinstance(row.get('text'),str)or not isinstance(row.get('at'),str):continue
  lines.append({'at':row['at'][:40],'stream':row['stream'],'text':redact(row['text'])[:8192]})
 return {'lines':lines,'available':True,'truncated':len(raw)>=_LIMIT}
