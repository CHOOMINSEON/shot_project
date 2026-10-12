"""Bounded out-of-order writes on POSIX and Windows NTFS."""
import os
from pathlib import Path


def mark_sparse(file):
    if os.name != 'nt':
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    control = kernel.DeviceIoControl
    control.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                        wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    control.restype = wintypes.BOOL
    returned = wintypes.DWORD()
    if not control(msvcrt.get_osfhandle(file.fileno()), 0x900C4, None, 0, None, 0, ctypes.byref(returned), None):
        error = ctypes.get_last_error()
        # FAT/exFAT can still store an ordinary file; existing free-space checks
        # reserve capacity for the complete upload, not just sparse chunks.
        if error not in [1, 50]:
            raise ctypes.WinError(error)


def allocated_bytes(path):
    path = Path(path)
    if os.name != 'nt':
        return path.stat().st_blocks * 512
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    measure = kernel.GetCompressedFileSizeW
    measure.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    measure.restype = wintypes.DWORD
    high = wintypes.DWORD()
    ctypes.set_last_error(0)
    low = measure(str(path.resolve()), ctypes.byref(high))
    if low == 0xFFFFFFFF and ctypes.get_last_error():
        raise ctypes.WinError(ctypes.get_last_error())
    return (high.value << 32) | low
