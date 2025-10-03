""" mbutane

mbutane is a wrapper for Butane that merges multiple human-readable
Butane Configs and translates them into machine-readable Ignition Configs.

Copyright (C) 2021-2025  Daniel Rudolf <https://www.daniel-rudolf.de>

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, version 3 of the License only.

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
this program. If not, see <http://www.gnu.org/licenses/>.

SPDX-License-Identifier: GPL-3.0-only
License-Filename: LICENSE
"""

import argparse, copy, datetime, errno, getpass, importlib.metadata, json, os, pathlib, re, socket, subprocess, sys, yaml
from collections import OrderedDict, UserDict
from collections.abc import Mapping, MutableMapping

__version__ = importlib.metadata.version("mbutane")
__copyright__ = "Copyright (C) 2021-2025 Daniel Rudolf"
__license__ = "GPL-3.0-only"


class YamlLoader(yaml.SafeLoader):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.add_constructor('tag:yaml.org,2002:map', self.construct_yaml_map.__func__)

    def construct_yaml_map(self, node):
        self.flatten_mapping(node)
        return OrderedDict(self.construct_pairs(node))


class YamlDumper(yaml.SafeDumper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.add_representer(OrderedDict, self.represent_ordered_dict.__func__)
        self.add_representer(JsonData, self.represent_str_dump.__func__)
        self.add_representer(YamlData, self.represent_str_dump.__func__)
        self.add_representer(YamlFile, self.represent_ordered_dict.__func__)
        self.add_representer(ButaneConfigFile, self.represent_ordered_dict.__func__)
        self.add_representer(ButaneConfig, self.represent_ordered_dict.__func__)

        self.add_representer(str, self.represent_str.__func__)

    def represent_ordered_dict(self, data):
        return self.represent_mapping('tag:yaml.org,2002:map', data.items())

    def represent_str_dump(self, data):
        return self.represent_scalar('tag:yaml.org,2002:str', data.dump(), style='|')

    def represent_str(self, data):
        if '\n' in data:
            return self.represent_scalar('tag:yaml.org,2002:str', data, style='|')
        return super().represent_str(data)


class JsonData(UserDict):
    @property
    def json(self):
        return self.dump()

    def dump(self, **options):
        options['indent'] = options.get('indent', 2)
        return (json.dumps(self.data, **options)
            + ("\n" if options['indent'] is not None else ""))


class YamlData(UserDict):
    @property
    def yaml(self):
        return self.dump()

    def dump(self, **options):
        options['default_flow_style'] = options.get('default_flow_style', False)
        return yaml.dump(self.data, Dumper=YamlDumper, **options)


class YamlFile(YamlData):
    _path = None

    _io = None
    _data = None

    def __init__(self, path):
        if not isinstance(path, pathlib.Path):
            raise ValueError("Invalid path given: Expecting pathlib.Path, got {!r}".format(path))
        if not path.exists():
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(path))
        if path.is_dir():
            raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), str(path))

        self._path = path

    @property
    def path(self):
        return str(self._path)

    @property
    def data(self):
        if self._data is None:
            self.load()

        return self._data

    @property
    def _file(self):
        if self._io is None:
            self.open()

        return self._io

    def __str__(self):
        return self.path

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return self.close()

    def open(self):
        self.close()

        try:
            self._io = self._path.open('r')
        except:
            self.close()
            raise

    def close(self):
        if self._io is not None:
            self._io.close()

        self._io = None
        self._data = None

    def load(self):
        self._data = yaml.load(self._file, Loader=YamlLoader)
        return self._data


class ButaneConfigFile(YamlFile):
    _storage = None

    def __init__(self, path, storageBasePath):
        super().__init__(pathlib.Path(path))

        if storageBasePath:
            self._storage = ButaneStorageConfig(pathlib.Path(storageBasePath))

    def open(self):
        super().open()

        if self._storage is not None:
            self._storage.open()

    def close(self):
        super().close()

        if self._storage is not None:
            self._storage.close()

    def load(self):
        super().load()

        if self._storage is not None:
            with self._storage as storage:
                self.update({'storage': storage.data})

        return self._data

    def update(self, other=None, **kwargs):
        self.__updateRecursively(self.data, other if other is not None else kwargs)

    def __updateRecursively(self, data, other):
        if isinstance(data, MutableMapping) and isinstance(other, Mapping):
            for key, value in other.items():
                if key in data and (isinstance(value, Mapping) or isinstance(value, list)):
                    self.__updateRecursively(data[key], value)
                else:
                    data[key] = value
        elif isinstance(data, list) and isinstance(other, list):
            data.extend(other)
        else:
            raise ValueError()


class ButaneConfig(ButaneConfigFile):
    _enableResultFile = True

    _resultFilePath = '/etc/.mbutane-result.json'
    _allowPaths = {'/etc', '/home', '/opt', '/root', '/srv', '/usr/local', '/var'}
    _failPaths = set()

    _mergeConfigs = None

    def __init__(self, enableResultFile=True):
        super().__init__(
            'config.bu',
            'src/main' if os.path.exists('src/main') else None
        )

        self._enableResultFile = enableResultFile
        self._failPaths = self._failPaths | {self._resultFilePath}

    def open(self):
        super().open()

        self._mergeConfigs = []

        mergeFilePaths = pathlib.Path('config.bu.d').glob('*.bu')
        mergeFilePaths = sorted(mergeFilePaths, key=lambda mergeFilePath: str(mergeFilePath))

        for mergeFilePath in mergeFilePaths:
            mergeStoragePath = pathlib.Path('src/').joinpath(mergeFilePath.stem)
            mergeConfig = ButaneConfigFile(
                mergeFilePath,
                mergeStoragePath if mergeStoragePath.exists() else None
            )

            self._mergeConfigs.append(mergeConfig)
            mergeConfig.open()

    def close(self):
        super().close()

        if self._mergeConfigs is not None:
            for mergeConfig in self._mergeConfigs:
                mergeConfig.close()

        self._mergeConfigs = None

    def load(self):
        super().load()

        self._data['storage'] = self._data.get('storage') or {}

        for mergeConfig in self._mergeConfigs:
            self.update(mergeConfig.data)

        self._data['storage']['directories'] = self._uniquePaths(self._data['storage'].get('directories') or [])
        self._data['storage']['files'] = self._uniqueFiles(self._data['storage'].get('files') or [])
        self._data['storage']['links'] = self._uniquePaths(self._data['storage'].get('links') or [])

        if not self._data['storage']['directories']:
            del self._data['storage']['directories']
        if not self._data['storage']['files']:
            del self._data['storage']['files']
        if not self._data['storage']['links']:
            del self._data['storage']['links']
        if not self._data['storage']:
            del self._data['storage']

        if self._enableResultFile:
            self._loadResultFile()

        return self._data

    def _loadResultFile(self):
        content = JsonData(OrderedDict([
            ('user', "{}@{}".format(getpass.getuser(), socket.gethostname())),
            ('date', datetime.datetime.now().astimezone().isoformat(timespec='seconds')),
        ]))

        config = OrderedDict([
            ('path', self._resultFilePath),
            ('contents', {'inline': content.dump()}),
            ('overwrite', True),
        ])

        self.update({'storage': {'files': [
            config
        ]}})

    def _assertValidPath(self, path):
        virtualPath = pathlib.PurePath(path)
        if any(virtualPath.match(failPath) for failPath in self._failPaths):
            raise ValueError("Cannot overwrite system file {!r}".format(path))
        if not any(virtualPath.is_relative_to(allowPath) for allowPath in self._allowPaths):
            raise ValueError("Cannot create file {!r} below read-only path".format(path))

    def _uniquePaths(self, paths):
        knownPaths = {}
        uniquePaths = []

        for path in paths:
            self._assertValidPath(path['path'])

            if path['path'] not in knownPaths:
                knownPaths[path['path']] = path
                uniquePaths.append(path)
            elif path != knownPaths[path['path']]:
                raise ValueError("Duplicate storage declaration of {!r}".format(path['path']))

        return uniquePaths

    def _uniqueFiles(self, paths):
        knownPaths = {}
        uniquePaths = []

        for path in paths:
            self._assertValidPath(path['path'])

            if path['path'] not in knownPaths:
                knownPaths[path['path']] = path
                uniquePaths.append(path)
            elif path != knownPaths[path['path']]:
                if 'contents' in path:
                    raise ValueError("Cannot overwrite already declared file {!r}".format(path['path']))

                appendContents = path.pop('append') if 'append' in path else []

                knownPath = {k: v for k, v in knownPaths[path['path']].items() if k not in {'contents', 'append'}}
                if path != knownPath:
                    raise ValueError("Unable to merge duplicate file declaration of {!r}".format(path['path']))

                if 'append' not in knownPaths[path['path']]:
                    knownPaths[path['path']]['append'] = appendContents
                else:
                    knownPaths[path['path']]['append'].extend(appendContents)

        return uniquePaths


class ButaneStorageConfig(UserDict):
    _basePath = None
    _configFileName = None
    _ignorePaths = {'/etc', '/home', '/opt', '/root', '/srv', '/usr', '/usr/local', '/var'}

    _storagePaths = None
    _storageConfigs = None
    _data = None

    def __init__(self, basePath, configFileName='subconfig.bu', ignorePaths={'.gitignore', '*~'}):
        if not isinstance(basePath, pathlib.Path):
            raise ValueError("Invalid path given: Expecting pathlib.Path, got {!r}".format(basePath))
        if not basePath.exists():
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(basePath))
        if not basePath.is_dir():
            raise NotADirectoryError(errno.ENOTDIR, os.strerror(errno.ENOTDIR), str(basePath))

        self._basePath = basePath
        self._configFileName = configFileName
        self._ignorePaths = self._ignorePaths | ignorePaths | {configFileName}

    @property
    def basePath(self):
        return str(self._basePath)

    @property
    def configFileName(self):
        return self._configFileName

    @property
    def paths(self):
        return [str(path) for path in self._paths]

    @property
    def configs(self):
        return [str(config) for config in self._configs]

    @property
    def data(self):
        if self._data is None:
            self.load()

        return self._data

    @property
    def _paths(self):
        if self._storagePaths is None:
            self.open()

        return self._storagePaths

    @property
    def _configs(self):
        if self._storageConfigs is None:
            self.open()

        return self._storageConfigs

    def __str__(self):
        return self.basePath

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return self.close()

    def open(self):
        self._storagePaths = self._basePath.glob('**/*')
        self._storagePaths = sorted(self._storagePaths, key=lambda storagePath: str(storagePath))

        self._storageConfigs = self._basePath.glob('**/' + self._configFileName)

    def close(self):
        self._storagePaths = None
        self._storageConfigs = None
        self._data = None

    def load(self):
        self._data = {'directories': [], 'files': [], 'links': []}

        self._loadPaths()
        self._loadConfigs()

        return self._data

    def _loadPaths(self):
        for path in self._paths:
            virtualPath = pathlib.PurePath('/').joinpath(path.relative_to(self._basePath))
            if any(virtualPath.match(ignorePath) for ignorePath in self._ignorePaths):
                continue

            config = OrderedDict()
            config['path'] = str(virtualPath)

            if path.is_symlink():
                config['target'] = os.readlink(str(path))
                self._data['links'].append(config)
            elif path.is_file():
                if path.stat().st_size > 0:
                    config['contents'] = {'local': str(path)}
                if os.access(str(path), os.X_OK):
                    config['mode'] = 0o755

                self._data['files'].append(config)
            elif path.is_dir():
                self._data['directories'].append(config)

    def _loadConfigs(self):
        for filePath in self._configs:
            basePath = '/' + str(filePath.relative_to(self._basePath).parent)

            with YamlFile(filePath) as file:
                if 'directories' in file.data:
                    for pathConfig in file.data['directories']:
                        self._applyPathConfig(self._data['directories'], pathConfig, basePath)
                if 'files' in file.data:
                    for pathConfig in file.data['files']:
                        self._applyPathConfig(self._data['files'], pathConfig, basePath)
                if 'links' in file.data:
                    for pathConfig in file.data['links']:
                        self._applyPathConfig(self._data['links'], pathConfig, basePath)

    def _applyPathConfig(self, configs, pathConfig, basePath):
        pathPattern = pathConfig.pop('path')
        for config in configs:
            try:
                path = pathlib.PurePath(config['path'])
                path = path.relative_to(basePath)
            except ValueError:
                continue

            path = pathlib.PurePath('/').joinpath(path)
            if path.match(pathPattern):
                config.update(copy.deepcopy(pathConfig))


def main():
    try:
        argumentParser = argparse.ArgumentParser(usage="%(prog)s [OPTION]... [PATH]", add_help=False,
                                                 description="mbutane is a wrapper for Butane that merges multiple " +
                                                             "human-readable Butane Configs and translates them into " +
                                                             "machine-readable Ignition Configs. ")
        argumentParser.epilog = ("Please report bugs using GitHub at <https://github.com/PhrozenByte/mbutane>. " +
                                 "Besides, you will find general help and information about mbutane there.")

        argumentGroup = argumentParser.add_argument_group("Arguments")
        argumentGroup.add_argument("path", metavar="PATH", nargs='?',
                                   help="Path to read Butane Configs from. Expects a 'config.bu' file as main Butane " +
                                        "config there and writes the transformed Ignition Configs to 'config.ign'. " +
                                        "Defaults to the current working dir.")

        applicationOptions = argumentParser.add_argument_group("Application options")
        applicationOptions.add_argument("--butane", dest="butane", action="store", default="butane",
                                        help="Path to the `butane` executable")
        applicationOptions.add_argument("--no-result-file", dest="resultFile", action="store_false",
                                        help="Don't create '/etc/.mbutane-result.json'")
        applicationOptions.add_argument("-v", "--verbose", dest="verbose", action="store_true",
                                        help="Print merged Butane Config before translation")

        helpOptions = argumentParser.add_argument_group("Help options")
        helpOptions.add_argument("--help", dest="help", action="store_true",
                                 help="Display this help message and exit")
        helpOptions.add_argument("--version", dest="version", action="store_true",
                                 help="Output version information and exit")

        args = argumentParser.parse_args()

        if args.help:
            argumentParser.print_help()
            sys.exit(0)

        if args.version:
            print("mbutane {}".format(__version__))
            print(__copyright__)
            print("")
            print("License GPLv3: GNU GPL version 3 only <http://gnu.org/licenses/gpl.html>.")
            print("This is free software: you are free to change and redistribute it.")
            print("There is NO WARRANTY, to the extent permitted by law.")
            print("")
            print("Written by Daniel Rudolf <http://www.daniel-rudolf.de/>")
            print("See also: <https://github.com/PhrozenByte/mbutane>")
            sys.exit(0)

        if args.path and args.path != '.':
            basePath = pathlib.Path(args.path)
            if not basePath.exists():
                print("Invalid base path {!r}: No such file or directory".format(str(basePath)), file=sys.stderr)
                sys.exit(1)
            if not basePath.is_dir():
                print("Invalid base path {!r}: Not a directory".format(str(basePath)), file=sys.stderr)
                sys.exit(1)

            os.chdir(str(basePath))

        butaneConfigFile = pathlib.Path('config.bu')
        if not butaneConfigFile.exists():
            print("Missing required {!r}: No such file or directory".format(str(butaneConfigFile)), file=sys.stderr)
            sys.exit(1)
        if not butaneConfigFile.is_file():
            print("Missing required {!r}: Not a file".format(str(butaneConfigFile)), file=sys.stderr)
            sys.exit(1)

        try:
            butaneCheckProcess = subprocess.run([args.butane, '--version'],
                                                stdout=subprocess.PIPE, check=True, encoding='utf-8')
            if not re.match(r"^Butane v?\d+\.\d+", butaneCheckProcess.stdout):
                print("Unable to run `butane`: `butane --version` returned an unexpected output", file=sys.stderr)
                sys.exit(1)
        except FileNotFoundError:
            print("Unable to run `butane`: No such executable", file=sys.stderr)
            sys.exit(1)
        except subprocess.CalledProcessError:
            print("Unable to run `butane`: `butane --version` failed with a non-zero exit status", file=sys.stderr)
            sys.exit(1)

        with ButaneConfig(args.resultFile) as butaneConfig:
            if args.verbose:
                print(butaneConfig.yaml)

            butaneProcess = subprocess.Popen([args.butane, '--pretty', '--strict', '--files-dir', '.'],
                                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                             encoding='utf-8')

            try:
                ignitionConfig, _ = butaneProcess.communicate(input=butaneConfig.yaml, timeout=300)
            except subprocess.TimeoutExpired:
                butaneProcess.kill()
                raise ChildProcessError(errno.ECHILD, 'Execution of `butane` timed out')

            if butaneProcess.returncode != 0:
                errorMessage = "Execution of `butane` failed with code {}".format(butaneProcess.returncode)
                raise ChildProcessError(errno.ECHILD, errorMessage)

            ignitionConfigFile = pathlib.Path('config.ign')
            ignitionConfigFile.write_text(ignitionConfig)

        return 0
    except KeyboardInterrupt:
        return 130

if __name__ == "__main__":
    main()
