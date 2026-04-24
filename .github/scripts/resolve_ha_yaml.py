#!/usr/bin/env python3
"""Resolve Home Assistant YAML includes and dump merged YAML to stdout.

Usage: python resolve_ha_yaml.py <file.yaml> [repo_root]
  repo_root defaults to the directory containing the script's parent (.github/..)
"""

import glob
import os
import sys

import yaml


def load_secrets(repo_root):
    path = os.path.join(repo_root, "fakesecrets.yaml")
    if os.path.isfile(path):
        with open(path) as f:
            data = yaml.safe_load(f)
            return data or {}
    return {}


def make_loader(base_dir, repo_root, secrets):
    class HALoader(yaml.SafeLoader):
        pass

    def _resolve(file_path):
        if not os.path.isfile(file_path):
            return None
        sub_base = os.path.dirname(os.path.abspath(file_path))
        loader_cls = make_loader(sub_base, repo_root, secrets)
        with open(file_path) as f:
            return yaml.load(f, Loader=loader_cls)

    def _yaml_files(dirpath):
        patterns = [os.path.join(dirpath, "*.yaml"), os.path.join(dirpath, "*.yml")]
        files = []
        for p in patterns:
            files.extend(glob.glob(p))
        return sorted(files)

    def handle_include(loader, node):
        rel = loader.construct_scalar(node)
        return _resolve(os.path.join(base_dir, rel))

    def handle_include_dir_named(loader, node):
        rel = loader.construct_scalar(node)
        dirpath = os.path.join(base_dir, rel)
        result = {}
        if os.path.isdir(dirpath):
            for fp in _yaml_files(dirpath):
                name = os.path.splitext(os.path.basename(fp))[0]
                result[name] = _resolve(fp)
        return result

    def handle_include_dir_merge_named(loader, node):
        rel = loader.construct_scalar(node)
        dirpath = os.path.join(base_dir, rel)
        result = {}
        if os.path.isdir(dirpath):
            for fp in _yaml_files(dirpath):
                data = _resolve(fp)
                if isinstance(data, dict):
                    result.update(data)
        return result

    def handle_include_dir_list(loader, node):
        rel = loader.construct_scalar(node)
        dirpath = os.path.join(base_dir, rel)
        result = []
        if os.path.isdir(dirpath):
            for fp in _yaml_files(dirpath):
                result.append(_resolve(fp))
        return result

    def handle_include_dir_merge_list(loader, node):
        rel = loader.construct_scalar(node)
        dirpath = os.path.join(base_dir, rel)
        result = []
        if os.path.isdir(dirpath):
            for fp in _yaml_files(dirpath):
                data = _resolve(fp)
                if isinstance(data, list):
                    result.extend(data)
        return result

    def handle_secret(loader, node):
        name = loader.construct_scalar(node)
        return secrets.get(name, f"SECRET_{name.upper()}")

    HALoader.add_constructor("!include", handle_include)
    HALoader.add_constructor("!include_dir_named", handle_include_dir_named)
    HALoader.add_constructor("!include_dir_merge_named", handle_include_dir_merge_named)
    HALoader.add_constructor("!include_dir_list", handle_include_dir_list)
    HALoader.add_constructor("!include_dir_merge_list", handle_include_dir_merge_list)
    HALoader.add_constructor("!secret", handle_secret)

    return HALoader


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <file.yaml> [repo_root]", file=sys.stderr)
        sys.exit(1)

    file_path = os.path.abspath(sys.argv[1])
    repo_root = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.dirname(
        os.path.dirname(os.path.dirname(file_path))
    )

    secrets = load_secrets(repo_root)
    base_dir = os.path.dirname(file_path)
    loader_cls = make_loader(base_dir, repo_root, secrets)

    with open(file_path) as f:
        data = yaml.load(f, Loader=loader_cls)

    print(yaml.dump(data, default_flow_style=False, allow_unicode=True), end="")


if __name__ == "__main__":
    main()
