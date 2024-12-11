"""Interfaces to locate executable files on file system."""

import itertools
import os
import time
from pathlib import Path

from xonsh.built_ins import XSH
from xonsh.lib.itertools import unique_everseen
from xonsh.platform import ON_WINDOWS


def get_possible_names(name, env=None):
    """Expand name to all possible variants based on `PATHEXT`.

    PATHEXT is a Windows convention containing extensions to be
    considered when searching for an executable file.

    Conserves order of any extensions found and gives precedence
    to the bare name.
    """
    env = env if env is not None else XSH.env
    extensions = list(env.get("PATHEXT", []))
    if not extensions:
        return [name]
    upper = name.upper() == name
    return [name] + [
        name + (ext.upper() if upper else ext.lower()) for ext in extensions
    ]


def clear_paths(paths):
    """Remove duplicates and nonexistent directories from paths."""
    return filter(os.path.isdir, unique_everseen(map(os.path.realpath, paths)))


def get_paths(env=None):
    """Return tuple with deduplicated and existent paths from ``$PATH``."""
    env = env if env is not None else XSH.env
    return tuple(reversed(tuple(clear_paths(env.get("PATH") or []))))


def is_file(filepath):
    """Check that ``filepath`` is file and exist."""
    if isinstance(filepath, str):
        filepath = Path(filepath)
    try:
        if filepath.is_file():
            return True
    except OSError:
        return False
    return False


def is_executable_in_windows(filepath, check_file_exist=True, env=None):
    """Check the file is executable in Windows.

    Parameters
    ----------
    filepath : str
        Path to file.
    check_file_exist : bool
        If ``False`` do not check that file exists. This helps to disable double checking in case the file already
        checked in upstream code. This is important for Windows where checking can take a long time.
    """
    filepath = Path(filepath)
    try:
        if check_file_exist and not is_file(filepath):
            return False
        env = env if env is not None else XSH.env
        return any(s.lower() == filepath.suffix.lower() for s in env.get("PATHEXT", []))
    except FileNotFoundError:
        # On Windows, there's no guarantee for the directory to really
        # exist even if isdir returns True. This may happen for instance
        # if the path contains trailing spaces.
        return False


def is_executable_in_posix(filepath, check_file_exist=True):
    """Check the file is executable in POSIX.

    Parameters
    ----------
    filepath : str
        Path to file.
    check_file_exist : bool
        If ``False`` do not check that file exists. This made to consistency with ``is_executable_in_windows``.
    """
    try:
        if check_file_exist and not is_file(filepath):
            return False
        return os.access(filepath, os.X_OK)
    except OSError:
        # broken Symlink are neither dir not files
        pass
    return False


is_executable = is_executable_in_windows if ON_WINDOWS else is_executable_in_posix


# --- Stable directory listing cache ---
# Directories listed in $XONSH_COMMANDS_CACHE_READ_DIR_ONCE are scanned
# once (on first access) and their file listings are cached as frozensets.
# Any $PATH entry that is under one of these prefixes gets cached.
# This turns per-file stat() calls into O(1) hash lookups.

_stable_dir_cache: dict[str, frozenset[str]] = {}
_stable_prefixes: tuple[str, ...] = ()
_stable_prefixes_source: tuple[str, ...] | None = None  # env snapshot


def _get_stable_prefixes() -> tuple[str, ...]:
    """Return lowered realpath prefixes from $XONSH_COMMANDS_CACHE_READ_DIR_ONCE.

    Re-reads the env var when its value changes (e.g. after ``.append()``).
    """
    global _stable_prefixes, _stable_prefixes_source
    env = XSH.env if XSH.env is not None else {}
    raw = env.get("XONSH_COMMANDS_CACHE_READ_DIR_ONCE", [])
    current = tuple(raw)
    if current != _stable_prefixes_source:
        _stable_prefixes_source = current
        _stable_prefixes = tuple(os.path.realpath(p).lower() for p in raw if p)
    return _stable_prefixes


def _is_stable_dir(path: str) -> bool:
    """Check if *path* is under one of the configured stable prefixes."""
    prefixes = _get_stable_prefixes()
    if not prefixes:
        return False
    rp = os.path.realpath(path).lower()
    return rp.startswith(prefixes)


_stable_dir_reported: set[str] = set()  # Paths already reported as "populate"


def _cached_dir_contains(path: str, filename: str):
    """For stable dirs: check *filename* via cached listing.

    Returns ``(found, populated)`` if the directory is (or was just) cached,
    or ``None`` if it is not a stable directory (caller should stat).

    *populated* is ``True`` on the first **hit** for a freshly-cached path
    (so debug output says "populate cache" on the lookup that actually
    benefits from the new cache, not on an earlier miss).
    """
    if path not in _stable_dir_cache:
        if not _is_stable_dir(path):
            return None
        try:
            files = frozenset(f.lower() for f in os.listdir(path))
        except OSError:
            return None
        _stable_dir_cache[path] = files
    found = filename.lower() in _stable_dir_cache[path]
    populated = False
    if found and path not in _stable_dir_reported:
        _stable_dir_reported.add(path)
        populated = True
    return found, populated


def locate_executable(name, env=None, use_path_cache=True, use_dir_session_cache=False):
    """Search executable binary name in ``$PATH`` and return full path."""
    return locate_file(
        name,
        env=env,
        check_executable=True,
        use_pathext=True,
        use_path_cache=use_path_cache,
        use_dir_session_cache=use_dir_session_cache,
    )


def is_explicit_path(name):
    """Return whether ``name`` is written as a path rather than a bare name.

    This follows the rule used by other shells: if the command name contains a
    path separator (``/``, or ``\\`` on Windows) it is an explicit path —
    resolved against the file system, relative to the current directory or as
    an absolute path, and **never** looked up in ``$PATH``. This covers
    ``./name``, ``../name``, ``~/name``, ``sub/name`` and absolute paths alike.

    A bare name with no separator (e.g. ``"binfile"``) is *not* an explicit
    path: it is resolved through ``$PATH`` and, for security reasons, never
    against the current working directory.
    """
    return os.sep in name or (os.altsep is not None and os.altsep in name)


class PathCache:
    is_dirty = True
    dir_cache = dict()

    @classmethod
    def get_clean(cls, env):
        if cls.is_dirty:
            env_path = env.get("PATH", [])
            cls.clean_paths = tuple(clear_paths(env_path))
            cls.is_dirty = False
        return cls.clean_paths

    @classmethod
    def get_dir_cached(cls, path):
        return cls.dir_cache.get(path,[])

    @classmethod
    def set_dir_cached(cls, path, file_list):
        cls.dir_cache[path] = file_list


def locate_file(
    name, env=None, check_executable=False, use_pathext=False, use_path_cache=True, use_dir_session_cache=False
):
    """Search file name in the current working directory and in ``$PATH`` and return full path.

    A name containing a path separator (``./name``, ``../name``, ``~/name``,
    ``sub/name`` or an absolute path) is an explicit path and is resolved
    *only* against the location it points at. If the file is not there the
    result is ``None`` — we must not fall back to a ``$PATH`` search, otherwise
    a command such as ``./name`` or ``sub/name`` would be located in ``$PATH``
    even though it does not exist in the current directory (see gh-6532). Only
    a bare name with no separator is looked up in ``$PATH``.
    """
    if is_explicit_path(name):
        return locate_relative_path(name, env, check_executable, use_pathext)
    return locate_file_in_path_env(
        name, env, check_executable, use_pathext, use_path_cache, use_dir_session_cache
    )


def locate_relative_path(name, env=None, check_executable=False, use_pathext=False):
    """Return absolute path for a name written as a path (containing a separator).

    We should not locate files without a separator (e.g. ``"binfile"``) for security reasons, like other shells.
    If the current directory has "binfile" it can be called only by providing a path such as "./binfile" explicitly.
    """
    p = Path(name)
    if is_explicit_path(name):
        possible_names = get_possible_names(p.name, env) if use_pathext else [p.name]
        for possible_name in possible_names:
            filepath = p.parent / possible_name
            try:
                if not is_file(filepath) or (
                    check_executable
                    and not is_executable(filepath, check_file_exist=False)
                ):
                    continue
                return str(filepath.absolute())
            except PermissionError:
                continue


def _cache_debug(msg):
    """Print trace message if $XONSH_COMMANDS_CACHE_TRACE is True."""
    env = XSH.env if XSH.env is not None else {}
    if not env.get("XONSH_COMMANDS_CACHE_TRACE", False):
        return
    from xonsh.tools import print_above_prompt

    print_above_prompt(msg)


from os import walk


def check_possible_name(path, possible_name, check_executable, check_file_exist):
    filepath = Path(path) / possible_name
    try:
        if not is_file(filepath) or (check_executable and
            not is_executable(filepath, check_file_exist)):
            return
        return str(filepath)
    except PermissionError:
        return


def locate_file_in_path_env(
    name, env=None, check_executable=False, use_pathext=False, use_path_cache=True, use_dir_session_cache=False
):
    """Search file name in ``$PATH`` and return full path.

    Compromise. There is no way to get case sensitive file name without listing all files.
    If the file name is ``CaMeL.exe`` and we found that ``camel.EXE`` exists there is no way
    to get back the case sensitive name. We don't want to read the list of files in all ``$PATH``
    directories because of performance reasons. So we're ok to get existent
    but case insensitive (or different) result from resolver.
    May be in the future file systems as well as Python Path will be smarter to get the case sensitive name.
    The task for reading and returning case sensitive filename we give to completer in interactive mode
    with ``commands_cache``.

    Typing speed boost: on Windows instead of checking that 10+ file.pathext files exist it's faster
    to scan a smaller dir and check whether those 10+ strings are in this list
    XONSH_DIR_CACHE_TO_LIST allows users to do just that
    """
    paths = []
    if env is None:
        env = XSH.env
        if use_path_cache:  # for generic environment: use cache only if configured
            paths = PathCache.get_clean(env)
        else:  #              otherwise              : clean paths every time
            env_path = env.get("PATH", [])
            paths = tuple(clear_paths(env_path))
    else:  #                  for custom  environment: clean paths every time
        env_path = env.get("PATH", [])
        paths = tuple(clear_paths(env_path))
    path_to_list = env.get("XONSH_DIR_CACHE_TO_LIST", [])
    dir_to_cache = env.get("XONSH_WIN_DIR_SESSION_CACHE", [])
    possible_names = get_possible_names(name, env) if use_pathext else [name]
    ext_count = len(possible_names)

    for path in paths:
        if path in dir_to_cache: # use session dir cache
            if not (f := PathCache.get_dir_cached(path)): # not cached, scan the dir ...
                for _dirpath, _dirnames, filenames in walk(path):
                    f.extend(filenames)
                    break  # no recursion into subdir
                PathCache.set_dir_cached(path, f) # ... and cache it
            for possible_name in possible_names:
                if possible_name not in f:
                    continue
                if found := check_possible_name(
                    path, possible_name, check_executable
                ):
                    return found
                else:
                    continue
        elif path in path_to_list and ext_count > 2: # list a dir vs checking many files
            f = []
            for _dirpath, _dirnames, filenames in walk(path):
                f.extend(filenames)
                break  # no recursion into subdir
            for possible_name in possible_names:
                if possible_name not in f:
                    continue
                if found := check_possible_name(
                    path, possible_name, check_executable, check_file_exist=False
                ):
                    return found
                else:
                    continue
        else: # check that file(s) exists individually
            for possible_name in possible_names:
                if found := check_possible_name(
                    path, possible_name, check_executable, check_file_exist=False
                ):
                    return found
                else:
                    continue
