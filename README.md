`mbutane`
=========

`mbutane` is a wrapper for [Butane][] that merges multiple human-readable Butane configs and translates them into machine-readable [Ignition][] configs.

Usage
-----

`mbutane` takes a path to a directory as only argument (defaults to the current working dir) and expects a `config.bu` as main Butane config file there. You can merge additional Butane config files into the resulting Ignition config by adding more `*.bu` files to the optional `config.bu.d` directory.

Optionally you can also create a `src/` directory with any number of file trees to be embedded in the Ignition config. `mbutane` will create entries for any file, directory, and link it finds there (excluding `.gitignore` files), including file contents and link targets. For the main `config.bu` you can use the `src/main/` directory. For any additional Butane config below `config.bu.d`, use a matching directory (e.g. use `src/my-user/` for `config.bu.d/my-user.bu`). File permissions and ownership are not preserved, except for executable files, which will receive `rwxr-xr-x` permissions by default.

To specify file permissions, ownership and whether existing files should be overwritten, you can use `subconfig.bu` files anywhere in the file tree. `subconfig.bu` are YAML files with the `files`, `directories`, and `links` mappings. They all expect a list of objects with a `path` pattern (a [`glob` pattern](https://en.wikipedia.org/wiki/Glob_(programming)) relative to the current directory) and optional `user`, `group`, `mode`, and `overwrite` keys matching those of a regular Butane config.

Here's an example of a `subconfig.bu` at `src/my-user/home/my-user/subconfig.bu`. It ensures that all files, directories and links below `/home/my-user` are owned by user `my-user`, that `/home/my-user` itself has permissions `0700` and all files below `/home/my-user/.local/bin` are executable (this would not have been necessary if the source files had been executable already).

```yaml
directories:
  - path: /
    mode: 0700
  - path: "*"
    user: { name: "my-user" }
    group: { name: "my-user" }
files:
  - path: /.local/bin/*
    mode: 0755
  - path: "*"
    user: { name: "my-user" }
    group: { name: "my-user" }
    overwrite: true
links:
  - path: "*"
    user: { name: "my-user" }
    group: { name: "my-user" }
    overwrite: true
```

The file tree is merged into `config.bu.d/my-user.bu`, which is later merged into the main `config.bu`. `mbutane` will then execute Butane and write the resulting Ignition config to `config.ign`. If this file exists already, it is overwritten.

Install
-------

`mbutane` is compatible with [PEP 517](https://peps.python.org/pep-0517/) and [PEP 518](https://peps.python.org/pep-0518/), which means you can (and should) install it with Python's [`pip`](https://pip.pypa.io/en/stable/):

```shell
python -m pip install .
```

`pip` will automatically download and install `mbutane`'s only Python dependency: [PyYAML](https://pyyaml.org/). Alternatively you can install PyYAML or a different, but compatible implementation with your distribution's package manger.

However, since `mbutane` is a wrapper for Butane, you must also install Butane locally. `mbutane` expects a `butane` executable in your `$PATH`, or you must give its path using the `--butane` option. You can either use Butane from your package sources, download one of Butane's release binaries, or use a container-based version of Butane. Please refer to [Butane's "Getting Started" docs](https://coreos.github.io/butane/getting-started/#getting-butane) for help.

`mbutane` was written for Python 3.8+ and last tested with Python 3.12, but should work with any later Python 3 version. If it doesn't, please file a bug report.

License & Copyright
-------------------

Copyright (C) 2021-2022  Daniel Rudolf &lt;https://www.daniel-rudolf.de&gt;

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, version 3 of the License only.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the [GNU General Public License](LICENSE) for more details.

[Butane]: https://coreos.github.io/butane/
[Ignition]: https://coreos.github.io/ignition/
