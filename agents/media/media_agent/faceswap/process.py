"""Bounded subprocess logs and process-tree lifetime, including parent death on Windows."""
import ctypes
from ctypes import wintypes
import os
import signal
import subprocess
import time


def run(command, *, cwd, env, log, check, timeout):
    windows_job = None
    kernel = None
    if os.name == 'nt':
        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', wintypes.DWORD), ('min_work', ctypes.c_size_t),
                        ('max_work', ctypes.c_size_t), ('active', wintypes.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                        ('scheduling', wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ('read_ops', 'write_ops', 'other_ops', 'read', 'write', 'other')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process_limit', ctypes.c_size_t),
                        ('job_limit', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        windows_job = kernel.CreateJobObjectW(None, None)
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not windows_job or not kernel.SetInformationJobObject(windows_job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            if windows_job:
                kernel.CloseHandle(windows_job)
            raise ctypes.WinError(ctypes.get_last_error())
    process = None
    try:
        with log.open('wb') as stream:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=stream, stderr=subprocess.STDOUT, start_new_session=os.name != 'nt',
                creationflags=(0x4 | subprocess.CREATE_NO_WINDOW) if os.name == 'nt' else 0)
            if windows_job:
                if not kernel.AssignProcessToJobObject(windows_job, wintypes.HANDLE(int(process._handle))):
                    raise ctypes.WinError(ctypes.get_last_error())
                ntdll = ctypes.WinDLL('ntdll')
                ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
                if ntdll.NtResumeProcess(wintypes.HANDLE(int(process._handle))) != 0:
                    raise RuntimeError('Could not resume FaceFusion process')
            started = time.monotonic()
            while process.poll() is None:
                check()
                if time.monotonic() - started > timeout:
                    raise TimeoutError('FaceFusion 처리 제한 시간을 초과했습니다.')
                if log.stat().st_size > 32 * 1024**2:
                    raise RuntimeError('FaceFusion 로그 제한을 초과했습니다.')
                time.sleep(.2)
            check()
            if process.returncode:
                # Detailed engine paths remain in the local log, not public API errors.
                raise RuntimeError('FaceFusion 처리가 실패했습니다. 입력 얼굴과 엔진 로그를 확인하세요.')
    finally:
        if windows_job:
            kernel.CloseHandle(windows_job)
        if process is not None:
            if os.name != 'nt':
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.poll() is None:
                process.kill()
            process.wait()
