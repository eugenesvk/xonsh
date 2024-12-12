"""Interfaces to locate executable files on file system."""

import os
import time
import pickle
import typing as tp
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
    return filter(os.path.isdir, unique_everseen(map(os.path.normpath, paths)))


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


class CmdPart:
    def __init__(self, *args, **kwargs):
        self.is_part: bool = False


def locate_executable(
    name,
    env=None,
    use_path_cache=True,
    use_dir_cache_session=False,
    use_dir_cache_perma=False,
    partial_match=None,
):
    """Search executable binary name in ``$PATH`` and return full path."""
    return locate_file(
        name,
        env=env,
        check_executable=True,
        use_pathext=True,
        use_path_cache=use_path_cache,
        use_dir_cache_session=use_dir_cache_session,
        use_dir_cache_perma=use_dir_cache_perma,
        partial_match=partial_match,
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


def executables_in(path) -> tp.Iterable[str]:
    """Returns a generator of files in path that the user could execute."""
    if ON_WINDOWS:
        func = _executables_in_windows
    else:
        func = _executables_in_posix
    try:
        yield from func(path)
    except PermissionError:
        return


def _executables_in_posix(path):
    if not os.path.exists(path):
        return
    else:
        yield from _yield_accessible_unix_file_names(path)


def _executables_in_windows(path):
    if not os.path.isdir(path):
        return
    try:
        for x in os.scandir(path):
            if is_executable_in_windows(x):
                yield x.name
    except FileNotFoundError:
        # On Windows, there's no guarantee for the directory to really
        # exist even if isdir returns True. This may happen for instance
        # if the path contains trailing spaces.
        return


def _yield_accessible_unix_file_names(path):
    """yield file names of executable files in path."""
    if not os.path.exists(path):
        return
    for file_ in os.scandir(path):
        if is_executable_in_posix(file_):
            yield file_.name


import threading


class _PathCmd(tp.NamedTuple):
    """A trie of executable files in a given dir with dir's timestamp for cache invalidation"""

    mtime: float
    ftrie: "pygtrie.CharTrie"  # trie[name.lower()] = name for case insensitive match


class PathCache:  # Singleton
    """Avoid IO during typing by caching:
    - cleaned paths (not files/cmds), refreshed per new prompt by setting .is_dirty
    - list of cmds in a "permanent" cache for unchanging dirs, pickled in a cache file
    - list of cmds in a "session" cache for rarely changing dirs
    also contains cleaned up user configured set of paths to cache (normalized, case-matching)
    """

    _instance: tp.Any | None = None
    _lock = threading.Lock()

    def __new__(cls, env):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
                    cls._instance.__is_init = False
        return cls._instance

    is_dirty = (
        True  # flag to signal that cleaned paths (not files/cmds) should be refreshed
    )
    dir_cache: dict[str, list[list[str]]] = dict()
    dir_key_cache: dict[str, _PathCmd] = dict()
    clean_paths: dict[str, tuple[str]] = dict()

    @classmethod
    def get_clean_path(cls, env):  # cleaned paths (not files/cmds)
        if cls.is_dirty:
            env_path = env.get("PATH", [])
            env_path_hash = hash_s_list(
                env_path
            )  # to test whether it matches PATH before
            # returning the cleaned version (avoid wrong cache for a env.swap(PATH=['a']))
            if env_path_hash not in cls.clean_paths:
                cls.clean_paths[env_path_hash] = tuple(clear_paths(env_path))
            cls.is_dirty = False
        return cls.clean_paths

    @classmethod
    def get_dir_cached(cls, path):  # dir_cache_session
        return cls.dir_cache.get(path, None)

    @classmethod
    def set_dir_cached(cls, path, f_trie):  # dir_cache_session
        cls.dir_cache[path] = f_trie

    @classmethod
    def get_dir_key_cache(cls, path):  # dir_cache_key
        return cls.dir_key_cache.get(path, None)

    @classmethod
    def set_dir_key_cache(cls, path, time, f_trie):  # dir_cache_key
        cls.dir_key_cache[path] = _PathCmd(time, f_trie)

    CACHE_FILE = "dir_perma_cache.pickle"

    def __init__(self, env) -> None:
        self.__is_init: bool
        if self.__is_init:
            return
        self.env = (
            env  # path to the cache file where all dir are cached for pre-loading
        )
        self._cache_file = None
        self._cmds_cache: pygtrie.CharTrie = pygtrie.CharTrie()
        self._dir_cache_perma: dict[str, pygtrie.CharTrie] = dict()
        self._pathext_cache: set = set()
        self._user_path_dirs_to_list: set = set()
        self.usr_dir_list_perma: set = set()
        self.usr_dir_list_session: set = set()
        self.usr_dir_list_key: set = set()
        # clean up user give list of dirs and cache it
        usr_dir_list_perma = [
            os.path.normpath(p).lower() for p in env.get("XONSH_DIR_PERMA_CACHE", [])
        ]
        usr_dir_list_session = [
            os.path.normpath(p).lower() for p in env.get("XONSH_DIR_SESSION_CACHE", [])
        ]
        usr_dir_list_key = [
            os.path.normpath(p).lower() for p in env.get("XONSH_DIR_CACHE_TO_LIST", [])
        ]
        env_path = env.get("PATH", [])
        for p in env_path:
            pn = os.path.normpath(p)
            pl = pn.lower()
            if pl in usr_dir_list_perma:
                self.usr_dir_list_perma.add(pn)
            if pl in usr_dir_list_session:
                self.usr_dir_list_session.add(pn)
            if pl in usr_dir_list_key:
                self.usr_dir_list_key.add(pn)
        self.__is_init = True

    @property
    def cache_file(self):
        """Keeping a property that lies on instance-attribute"""
        env = self.env
        if (
            self._cache_file is None
        ):  # path to the cache file where all dir are cached for pre-loading
            if "XONSH_CACHE_DIR" in env and "XONSH_DIR_PERMA_CACHE" in env:
                self._cache_file = (
                    Path(env["XONSH_CACHE_DIR"]).joinpath(self.CACHE_FILE).resolve()
                )
            else:
                self._cache_file = ""  # set a falsy value other than None
        return self._cache_file

    def get_dir_cache_perma(self):
        """Get a list of valid commands per path in a trie data structure for partial matching"""
        self.update_cache()
        return self._dir_cache_perma

    def update_cache(self):
        """The main function to update commands cache"""
        env = self.env
        env_path = env.get("PATH", [])
        env_path_hash = hash_s_list(env_path)
        paths_dict = self.get_clean_path(env)
        if env_path_hash in paths_dict:
            paths = paths_dict[env_path_hash]
        else:
            paths = tuple(clear_paths(env_path))
            PathCache.clean_paths[env_path_hash] = paths

        if self._update_paths_cache(
            paths
        ):  # not yet needed since only a few dirs are supported
            pass
        #     all_cmds = pygtrie.CharTrie()
        #     for cmd_low, cmd, path in self._iter_binaries(reversed(paths)): # iterate backwards for entries @ PATH front to overwrite entries at the back
        #         all_cmds[cmd_low] = (cmd,path)
        #     self._cmds_cache = all_cmds
        # return self._cmds_cache

    def _update_paths_cache(self, paths: tp.Sequence[str]) -> bool:
        """load cached results or update cache"""
        if (not self._dir_cache_perma) and self.cache_file and self.cache_file.exists():
            try:  # 1st time: load the commands from cache-file if configured
                self._dir_cache_perma, self._pathext_cache = pickle.loads(
                    self.cache_file.read_bytes()
                ) or [{}, set()]
            except Exception:
                self.cache_file.unlink(missing_ok=True)  # the file is corrupt
        updated = False
        pathext = set(self.env.get("PATHEXT", [])) if ON_WINDOWS else []
        for path in paths:  # ↓ user-configured to be cached
            if (path in self.usr_dir_list_perma) and (
                (path not in self._dir_cache_perma)  # ← not in cache
                or (pathext and (not pathext == self._pathext_cache))
            ):  # ← definition of an executable changed
                cmd_chartrie = pygtrie.CharTrie()
                for cmd in executables_in(path):
                    cmd_chartrie[cmd.lower()] = (
                        cmd  # lower case for case-insensitive search, but preserve case
                    )
                self._dir_cache_perma[path] = cmd_chartrie
                self._pathext_cache = set(pathext)
                updated = True
        if updated and self.cache_file:
            self.cache_file.write_bytes(
                pickle.dumps([self._dir_cache_perma, self._pathext_cache])
            )
        return updated

    def _iter_binaries(self, paths):
        for path in paths:
            for cmd_low in (cmd_chartrie := self._dir_cache_perma.get(path, [])):
                cmd = cmd_chartrie[cmd_low]
                yield cmd_low, cmd, os.path.join(path, cmd)


def locate_file(
    name,
    env=None,
    check_executable=False,
    use_pathext=False,
    use_path_cache=True,
    use_dir_cache_session=False,
    use_dir_cache_perma=False,
    partial_match=None,
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
        name,
        env,
        check_executable,
        use_pathext,
        use_path_cache,
        use_dir_cache_session,
        use_dir_cache_perma,
        partial_match,
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
        if check_file_exist and not is_file(filepath):
            return
        if check_executable and not is_executable(filepath, check_file_exist=False):
            return
        return str(filepath)
    except PermissionError:
        return


import hashlib
import struct


def hash_s_list(s_list):
    """
    Serialize a list of strings and hash them using sha256
    """
    hash_o = hashlib.sha256()
    for s in s_list:  # Hash each string
        length_encoded = struct.pack("I", len(s))
        hash_o.update(length_encoded)
        hash_o.update(s.encode("utf-8"))
    return hash_o.hexdigest()


import pygtrie


def locate_file_in_path_env(
    name,
    env=None,
    check_executable=False,
    use_pathext=False,
    use_path_cache=True,
    use_dir_cache_session=False,
    use_dir_cache_perma=False,
    partial_match=None,
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
    When listing a XONSH_DIR_CACHE_TO_LIST dir or using a XONSH_DIR_SESSION_CACHE cache of a dir listing,
    we can get case sensitive file name.

    Typing speed boost: on Windows instead of checking that 10+ file.pathext files exist it's faster
    to scan a smaller dir and check whether those 10+ strings are in this list
    XONSH_DIR_CACHE_TO_LIST allows users to do just that
    XONSH_DIR_SESSION_CACHE further allows to list a dir and cache the results to avoid
    doing any IO on subsequent calls
    XONSH_DIR_PERMA_CACHE further allows to list larger constant dirs like Windows/System32
    and cache the results until OS is updated to avoid doing any IO
    """
    paths = []
    if env is None:
        env = XSH.env
        env_path = env.get("PATH", [])
        if use_path_cache:  # for generic environment: use cache only if configured
            paths_dict = PathCache.get_clean_path(env)
            env_path_hash = hash_s_list(env_path)
            if env_path_hash in paths_dict:
                paths = paths_dict[env_path_hash]
            else:
                paths = tuple(clear_paths(env_path))
                PathCache.clean_paths[env_path_hash] = paths
        else:  #              otherwise              : clean paths every time
            paths = tuple(clear_paths(env_path))
    else:  #                  for custom  environment: clean paths every time
        env_path = env.get("PATH", [])
        paths = tuple(clear_paths(env_path))
    pc = PathCache(env)
    usr_dir_list_perma = pc.usr_dir_list_perma
    usr_dir_list_session = pc.usr_dir_list_session
    usr_dir_list_key = pc.usr_dir_list_key
    if usr_dir_list_perma:
        dir_cache_perma = (
            pc.get_dir_cache_perma()
        )  # path → cmd_chartrie[cmd.lower()] = cmd
    possible_names = get_possible_names(name, env) if use_pathext else [name]
    ext_count = len(possible_names)
    ext_min = int(env.get("XONSH_DIR_CACHE_LIST_EXT_MIN", 3))
    skip_exist = env.get(
        "XONSH_DIR_CACHE_SKIP_EXIST", False
    )  # avoid dupe is_file check since we assume permanent/session caches don't change ever/per session

    for path in paths:
        if (
            check_executable
            and use_dir_cache_perma
            and usr_dir_list_perma
            and path in usr_dir_list_perma
            and path in dir_cache_perma
        ):
            cmd_chartrie = dir_cache_perma[path]
            for possible_name in possible_names:
                possible_Name = cmd_chartrie.get(possible_name.lower())
                if possible_Name is not None:  #          ✓ full match
                    if found := check_possible_name(
                        path, possible_Name, check_executable, check_file_exist=skip_exist
                    ):
                        return found
                    else:
                        continue
            if cmd_chartrie.has_subtrie(name.lower()):  # ± partial match
                if isinstance(
                    partial_match, CmdPart
                ):  # report partial match for color highlighting
                    partial_match.is_part = True
        elif (
            use_dir_cache_session
            and usr_dir_list_session
            and path in usr_dir_list_session
        ):  # use session dir cache
            f_trie = PathCache.get_dir_cached(path)
            if not f_trie:  # not cached, scan the dir ...
                f_trie = pygtrie.CharTrie()
                for _dirpath, _dirnames, filenames in walk(path):
                    for fname in filenames:
                        f_trie[fname.lower()] = fname  # for case-insensitive match
                    break  # no recursion into subdir
                PathCache.set_dir_cached(path, f_trie)  # ... and cache it
            for possible_name in possible_names:
                possible_Name = f_trie.get(possible_name.lower())
                if possible_Name is not None:  #          ✓ full match
                    if found := check_possible_name(
                        path, possible_Name, check_executable, check_file_exist=skip_exist
                    ):
                        return found
                    else:
                        continue
            if f_trie.has_subtrie(name.lower()):  # ± partial match
                if isinstance(
                    partial_match, CmdPart
                ):  # report partial match for color highlighting
                    partial_match.is_part = True
        elif (
            ext_count >= ext_min and usr_dir_list_key and path in usr_dir_list_key
        ):  # list a dir vs checking many files (cached by mtime)
            path_time = os.path.getmtime(path)
            path_cmd = PathCache.get_dir_key_cache(path)
            use_cache = True if path_cmd and (path_cmd.mtime == path_time) else False
            if use_cache:
                ftrie = path_cmd.ftrie
            else:  # rebuild dir cache
                ftrie = pygtrie.CharTrie()
                for _dirpath, _dirnames, filenames in walk(path):
                    for fname in filenames:
                        ftrie[fname.lower()] = fname  # for case-insensitive match
                    break  # no recursion into subdir
                PathCache.set_dir_key_cache(path, path_time, ftrie)
            for possible_name in possible_names:
                possible_Name = ftrie.get(possible_name.lower())
                if possible_Name is not None:  #          ✓ full match
                    if found := check_possible_name(
                        path, possible_Name, check_executable, check_file_exist=False
                    ):  # avoid dupe is_file check since we already got a list of files
                        return found
                    else:
                        continue
            if ftrie.has_subtrie(name.lower()):  # ± partial match
                if isinstance(
                    partial_match, CmdPart
                ):  # report partial match for color highlighting
                    partial_match.is_part = True
        else:  # check that file(s) exists individually
            for possible_name in possible_names:
                if found := check_possible_name(path, possible_name, check_executable, check_file_exist=False):
                    return found
                else:
                    continue
