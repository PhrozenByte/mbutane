""" mbutane

mbutane is a wrapper for Butane that merges multiple human-readable
Butane Configs and translates them into machine-readable Ignition Configs.

Copyright (C) 2021  Daniel Rudolf <https://www.daniel-rudolf.de>

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

import copy, errno, os, pathlib, yaml
from collections import OrderedDict, UserDict, Mapping, MutableMapping

__version__ = "0.0.2"
__copyright__ = "Copyright (C) 2021 Daniel Rudolf"
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

        self.add_representer(ButaneConfigFile, self.represent_ordered_dict.__func__)
        self.add_representer(ButaneConfig, self.represent_ordered_dict.__func__)
        self.add_representer(YamlFile, self.represent_ordered_dict.__func__)
        self.add_representer(OrderedDict, self.represent_ordered_dict.__func__)

        self.add_representer(str, self.represent_str.__func__)

    def represent_ordered_dict(self, data):
        return self.represent_mapping('tag:yaml.org,2002:map', data.items())

    def represent_str(self, data):
        if '\n' in data:
            return self.represent_scalar('tag:yaml.org,2002:str', data, style='|')
        return super().represent_str(data)

class YamlFile(UserDict):
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
    def yaml(self):
        return self.dump()

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

    def dump(self, **options):
        options['default_flow_style'] = bool(options.get('default_flow_style', False))
        return yaml.dump(self.data, Dumper=YamlDumper, **options)

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
    _mergeConfigs = None

    def __init__(self):
        super().__init__(
            'config.bu',
            'src/main' if os.path.exists('src/main') else None
        )

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

        for mergeConfig in self._mergeConfigs:
            self.update(mergeConfig.data)

        self._data['storage']['directories'] = self._uniquePaths(self._data['storage']['directories'])
        self._data['storage']['files'] = self._uniqueFiles(self._data['storage']['files'])
        self._data['storage']['links'] = self._uniquePaths(self._data['storage']['links'])

        return self._data

    def _uniquePaths(self, paths):
        knownPaths = {}
        uniquePaths = []

        for path in paths:
            if path['path'] not in knownPaths:
                knownPaths[path['path']] = path
                uniquePaths.append(path)
            elif path != knownPaths[path['path']]:
                raise ValueError()

        return uniquePaths

    def _uniqueFiles(self, paths):
        knownPaths = {}
        uniquePaths = []

        for path in paths:
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
    _ignorePaths = {'/*', '/usr/*', '/var/*'}

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
                    config['contents'] = {'local': str(path) }

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
