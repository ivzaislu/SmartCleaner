"""No-overwrite, same-volume moves for the quarantine."""

import ctypes
import os
import stat
from contextlib import ExitStack, contextmanager

from smartcleaner.protection import inspect_path


def identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_nlink


if os.name == "nt":
    import msvcrt
    from ctypes import wintypes as w

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel.CreateFileW
    create_file.argtypes = (w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID,
                            w.DWORD, w.DWORD, w.HANDLE)
    create_file.restype = w.HANDLE
    close_handle = kernel.CloseHandle
    close_handle.argtypes = (w.HANDLE,)
    close_handle.restype = w.BOOL
    get_info = kernel.GetFileInformationByHandleEx
    get_info.argtypes = (w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD)
    get_info.restype = w.BOOL
    set_info = kernel.SetFileInformationByHandle
    set_info.argtypes = (w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD)
    set_info.restype = w.BOOL

    class RenameInfo(ctypes.Structure):
        _fields_ = [("replace", w.DWORD), ("root", w.HANDLE),
                    ("length", w.DWORD), ("name", w.WCHAR * 1)]

    def open_handle(path, access, share, flags):
        handle = create_file(str(path), access, share, None, 3, flags, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def reject_reparse_handle(handle):
        # FileAttributeTagInfo consists of file attributes and a reparse tag.
        info = (w.DWORD * 2)()
        if not get_info(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if info[0] & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("Reparse point is blocked")

    @contextmanager
    def locked_move(source, destination):
        with ExitStack() as stack:
            parents = dict.fromkeys((*reversed(source.parents), *reversed(destination.parents)))
            for parent in parents:
                handle = open_handle(parent, 0, 3, 0x02200000)
                stack.callback(close_handle, handle)
                reject_reparse_handle(handle)
            # GENERIC_READ | DELETE, share read only, OPEN_REPARSE_POINT.
            handle = open_handle(source, 0x80010000, 1, 0x00200000)
            try:
                reject_reparse_handle(handle)
                descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
            except (OSError, ValueError):
                close_handle(handle)
                raise
            stack.callback(os.close, descriptor)

            def move():
                name = str(destination).encode("utf-16-le")
                buffer = ctypes.create_string_buffer(RenameInfo.name.offset + len(name) + 2)
                info = RenameInfo.from_buffer(buffer)
                info.length = len(name)
                ctypes.memmove(ctypes.addressof(buffer) + RenameInfo.name.offset, name, len(name))
                if not set_info(handle, 3, buffer, len(buffer)):
                    raise ctypes.WinError(ctypes.get_last_error())

            yield descriptor, move

else:
    def open_parent(path, stack):
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = os.open(path.anchor, flags)
        stack.callback(os.close, descriptor)
        for name in path.parts[1:-1]:
            descriptor = os.open(name, flags, dir_fd=descriptor)
            stack.callback(os.close, descriptor)
        return descriptor

    @contextmanager
    def locked_move(source, destination):
        with ExitStack() as stack:
            src_parent = open_parent(source, stack)
            dst_parent = open_parent(destination, stack)
            descriptor = os.open(source.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=src_parent)
            stack.callback(os.close, descriptor)
            rename = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
            if rename is None:
                raise OSError("Atomic no-overwrite rename unavailable")
            rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
                               ctypes.c_uint)
            rename.restype = ctypes.c_int

            def rename_entry(src, src_fd, dst, dst_fd):
                if rename(src_fd, os.fsencode(src), dst_fd, os.fsencode(dst), 1):
                    error = ctypes.get_errno()
                    raise OSError(error, os.strerror(error))

            def move():
                for path, parent in ((source, src_parent), (destination, dst_parent)):
                    current = inspect_path(path.parent)
                    if not os.path.samestat(current, os.fstat(parent)):
                        raise ValueError("Parent directory changed before move")
                expected = identity(os.fstat(descriptor))
                if identity(os.stat(source.name, dir_fd=src_parent, follow_symlinks=False)) != expected:
                    raise ValueError("Source changed before move")
                rename_entry(source.name, src_parent, destination.name, dst_parent)
                actual = os.stat(destination.name, dir_fd=dst_parent, follow_symlinks=False)
                if identity(actual) != expected:
                    try:
                        rename_entry(destination.name, dst_parent, source.name, src_parent)
                    except OSError as exc:
                        raise OSError(f"Source changed and rollback failed. Inspect {destination}") from exc
                    raise ValueError("Source changed during move and was returned")

            yield descriptor, move
