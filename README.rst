This fork adds the ability to have no input lag on Windows and also run ``.xsh`` files without a ``[WinError 193] %1 is not a valid Win32 application`` error for testing until they are hopefully merged into main.

TLDR: add some dirs from ``$PATH`` to:

- ``$XONSH_DIR_PERMA_CACHE``: unchanging dirs like ``C:\Windows\System32\`` for permanent caching
- ``$XONSH_DIR_CACHE_TO_ALIST``: dirs with (almost) all executables, faster vs ↓
- ``$XONSH_DIR_CACHE_TO_LIST``: small dirs (a few dozen files) for full file listing
- ``$XONSH_DIR_SESSION_CACHE``: rarely changing dirs for caching per Xonsh session

Run ``from xonsh.procs.executables import PathCache; pc = PathCache; pc.help_me_choose()`` to see auto-suggestions re. which dirs from ``$PATH`` could be added to which cache.
And ``from xonsh.procs.executables import PathCache; pc = PathCache(None); pc.get_cache_info(v=2)`` for a detailed overview of which dirs are cached where.

------

Reduce typing delay
^^^^^^^^^^^^^^^^^^^

Typing can be slow due to testing whether the typed text is an executable file
(for color highlighting), which tests whether a file exists:

- for each of the dozen of dirs in ``PATH``

- for each of 15+ file.pathext

For smaller dirs (~few dozen files) it's faster to list the dir and check whether each file is an executable, so you can add such dirs to ``$XONSH_DIR_CACHE_TO_LIST`` to reduce typing lag. But even for bigger dirs, since the list is cached until the dir changes, and the cache is updated on prompt refresh instead of on each typed char, it still makes sense to add them to the cache. And for dirs with (almost) all executable files you can skip checking whether each file is an executable, which is much faster, so it's better adding such dirs to ``$XONSH_DIR_CACHE_TO_ALIST``.

And to reduce the typing lag even more (at the cost of a small loss of precision of syntax highlighting) you can list all the rarely changing (like ``C:\Program Files\Python\``) or not very important dirs from your ``$PATH`` in ``$XONSH_DIR_SESSION_CACHE``
This will cache a list of files within these dirs per Xonsh session and thus avoid any IO checks on subsequent typing. However, if Xonsh or any other process changes the list of files in these dirs, you'll lose the accuracy of syntax highlighting since the cache will not be updated to reflect it

You can also cache large never changing dirs (like ``C:\Windows\System32\`` with thousands of files) permanently by adding them to
``$XONSH_DIR_PERMA_CACHE`` (stored in ``$XONSH_CACHE_DIR\dir_perma_cache.pickle``)

And for a tiny extra boost you can set ``XONSH_DIR_CACHE_SKIP_EXIST`` to ``True`` to skip an extra
IO operation by not checking for whether a file exists in the permanent/session cached dirs

Set ``$XONSH_DIR_CACHE_LIST_SAVE_ON_EXIT`` to further reduce the need to update caches by saving them to file and reloading on startup

------

Highlighting of valid partial commands
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Besides speed (that's mostly relevant to Windows), adding some dirs to any of the cache env vars allows xonsh to know whether your incomplete command is a prefix of a valid command (and highlight i̲t̲) or not — great for catching early typos!

https://github.com/user-attachments/assets/b8138c98-614a-4b94-9696-e5e80f4b0a15

------

xonsh
=====

.. class:: center

    **xonsh** is a Python-powered shell. Full-featured and cross-platform. The language is a superset of Python 3.6+ with additional shell primitives.  Xonsh word was made from *conch* (🐚, *@*) and indicates belonging to the command shells world.


.. list-table::
   :widths: 1 1

   *  -  **Xonsh is the Shell**
      -  **Xonsh is Python**

   *  -  .. code-block:: shell

            cd $HOME

            id $(whoami)

            cat /etc/passwd | grep root > ~/root.txt

            $PROMPT = '@ '


      -  .. code-block:: python

            2 + 2

            var = "hello".upper()

            import json; json.loads('{"a":1}')

            [i for i in range(0,10)]

   *  -  **Xonsh is the Shell in Python**
      -  **Xonsh is Python in the Shell**

   *  -  .. code-block:: python

            len($(curl -L https://xon.sh))

            $PATH.append('/tmp')

            p'/etc/passwd'.read_text().find('root')

            xontrib load dalias
            id = $(@json docker ps --format json)['ID']

      -  .. code-block:: python

            name = 'foo' + 'bar'.upper()
            echo @(name) > /tmp/@(name)

            ls @(input('file: '))
            touch @([f"file{i}" for i in range(0,10)])

            aliases['e'] = 'echo @(2+2)'
            aliases['a'] = lambda args: print(args)


If you like xonsh, :star: the repo, `write a tweet`_ and stay tuned by watching releases.

.. class:: center

    .. image:: https://img.shields.io/badge/Zulip%20Community-xonsh-green
            :target: https://xonsh.zulipchat.com/join/hbvue5rimpdkwkdjuiqfs7tv/
            :alt: Join to xonsh.zulipchat.com

    .. image:: https://github.com/xonsh/xonsh/actions/workflows/test.yml/badge.svg
            :target: https://github.com/xonsh/xonsh/actions/workflows/test.yml
            :alt: GitHub Actions

    .. image:: https://codecov.io/gh/xonsh/xonsh/branch/master/graphs/badge.svg?branch=main
            :target: https://codecov.io/github/xonsh/xonsh?branch=main
            :alt: codecov.io

    .. image:: https://repology.org/badge/tiny-repos/xonsh.svg
            :target: https://repology.org/project/xonsh/versions
            :alt: repology.org


First steps
***********

Install xonsh from pip:

.. code-block:: xonshcon

    python -m pip install 'xonsh[full]'

And visit https://xon.sh for more information:

- `Installation <https://xon.sh/contents.html#installation>`_ - using packages, docker or AppImage.
- `Tutorial <https://xon.sh/tutorial.html>`_ - step by step introduction in xonsh.

Extensions
**********

Xonsh has an extension/plugin system.  We call these additions ``xontribs``.

- `Xontribs on Github <https://github.com/topics/xontrib>`_
- `Awesome xontribs <https://github.com/xonsh/awesome-xontribs>`_
- `Core xontribs <https://xon.sh/api/_autosummary/xontribs/xontrib.html>`_
- `Create a xontrib step by step from template <https://github.com/xonsh/xontrib-template>`_

Projects that use xonsh or compatible
*************************************

- `conda <https://conda.io/projects/conda/en/latest/>`_ and `mamba <https://mamba.readthedocs.io/en/latest/>`_: Modern package managers.
- `Starship <https://starship.rs/>`_: Cross-shell prompt.
- `zoxide <https://github.com/ajeetdsouza/zoxide>`_: A smarter cd command.
- `gitsome <https://github.com/donnemartin/gitsome>`_: Supercharged Git/shell autocompleter with GitHub integration.
- `xxh <https://github.com/xxh/xxh>`_: Using xonsh wherever you go through the SSH.
- `any-nix-shell <https://github.com/haslersn/any-nix-shell>`_: xonsh support for the ``nix run`` and ``nix-shell`` environments of the Nix package manager.
- `lix <https://github.com/lix-project/lix>`_: A modern, delicious implementation of the Nix package manager.
- `x-cmd <https://www.x-cmd.com/>`_: x-cmd is a vast and interesting collection of tools guided by the Unix philosophy.
- `rever <https://regro.github.io/rever-docs/>`_: Cross-platform software release tool.
- `Regro autotick bot <https://github.com/regro/cf-scripts>`_: Regro Conda-Forge autoticker.

Jupyter-based interactive notebooks via `xontrib-jupyter <https://github.com/xonsh/xontrib-jupyter>`_:

- `Jupyter and JupyterLab <https://jupyter.org/>`_: Interactive notebook platform.
- `euporie <https://github.com/joouha/euporie>`_: Terminal based interactive computing environment.
- `Jupytext <https://jupytext.readthedocs.io/>`_: Clear and meaningful diffs when doing Jupyter notebooks version control.

The xonsh shell community
*************************

The xonsh shell is developed by a community of volunteers. There are a few ways to help out:

- Solve a `popular issue <https://github.com/xonsh/xonsh/issues?q=is%3Aissue+is%3Aopen+sort%3Areactions-%2B1-desc>`_ or `high priority issue <https://github.com/xonsh/xonsh/issues?q=is%3Aopen+is%3Aissue+label%3Apriority-high+sort%3Areactions-%2B1-desc>`_ or a `good first issue <https://github.com/xonsh/xonsh/issues?q=is%3Aopen+is%3Aissue+label%3A%22good+first+issue%22+sort%3Areactions-%2B1-desc>`_. You can start with the `Developer guide <https://xon.sh/devguide.html>`_.
- Take an `idea <https://github.com/xonsh/xontrib-template/issues?q=is%3Aopen+is%3Aissue+label%3Aidea+sort%3Areactions-%2B1-desc>`_ and `create a new xontrib <https://github.com/xonsh/xontrib-template#why-use-this-template>`_.
- Contribute to `xonsh API <https://github.com/xonsh/xonsh/tree/main/xonsh/api>`_.
- Become xonsh core developer by deep diving into xonsh internals. E.g. we feel a lack of Windows support.
- `Become a sponsor to xonsh <https://github.com/sponsors/xonsh>`_.
- `Write a tweet`_, post or an article to spread the good word about xonsh in the world.
- Give a star to xonsh repository and to `xontribs <https://github.com/topics/xontrib>`_ you like.

We welcome new contributors!

.. _write a tweet: https://twitter.com/intent/tweet?text=xonsh%20is%20a%20Python-powered,%20cross-platform,%20Unix-gazing%20shell%20language%20and%20command%20prompt.&url=https://github.com/xonsh/xonsh

Credits
*******

- Thanks to `Zulip <https://zulip.com/>`_ for supporting the xonsh community!
