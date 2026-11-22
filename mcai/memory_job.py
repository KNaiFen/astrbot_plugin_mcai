"""Windows aggregate commit limit for the auxiliary process tree."""

import ctypes
import uuid
from ctypes import wintypes as w


class Basic(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_longlong),
        ("job_time", ctypes.c_longlong),
        ("flags", w.DWORD),
        ("minimum", ctypes.c_size_t),
        ("maximum", ctypes.c_size_t),
        ("active", w.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority", w.DWORD),
        ("scheduling", w.DWORD),
    ]


class IO(ctypes.Structure):
    _fields_ = [("counter" + str(i), ctypes.c_ulonglong) for i in range(6)]


class Extended(ctypes.Structure):
    _fields_ = [
        ("basic", Basic),
        ("io", IO),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process", ctypes.c_size_t),
        ("peak_job", ctypes.c_size_t),
    ]


def kernel():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
    api.CreateJobObjectW.restype = w.HANDLE
    api.OpenJobObjectW.argtypes = [w.DWORD, w.BOOL, w.LPCWSTR]
    api.OpenJobObjectW.restype = w.HANDLE
    api.GetCurrentProcess.restype = w.HANDLE
    api.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    api.SetInformationJobObject.argtypes = [
        w.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        w.DWORD,
    ]
    api.CloseHandle.argtypes = [w.HANDLE]
    return api


class MemoryJob:
    def __init__(self, mib=None):
        self.limit_mib = mib
        self.api = kernel()
        self.name = "Local\\MCAI-operations-" + uuid.uuid4().hex
        self.handle = self.api.CreateJobObjectW(None, self.name)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = Extended()
        info.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE, including detached descendants.
        if mib is not None:
            info.basic.flags |= 0x200  # JOB_MEMORY on the aggregate parent only.
            info.job_memory = mib * 1024**2
        if not self.api.SetInformationJobObject(
            self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def close(self):
        handle, self.handle = self.handle, None
        if handle:
            self.api.CloseHandle(handle)


def join(name):
    api = kernel()
    handle = api.OpenJobObjectW(1, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not api.AssignProcessToJobObject(handle, api.GetCurrentProcess()):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        # The owner retains the handle; closing it ends all joined descendants.
        api.CloseHandle(handle)
