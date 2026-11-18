#!/usr/bin/env python3
"""Describe and stage captured skill packages without running their contents.

This is a deliberately narrow producer profile, not a generic native client.
Staging proves byte/mode correspondence and supported Markdown references;
operational resource closure always remains unchecked.
"""

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from types import MappingProxyType
from typing import Mapping, Optional, Tuple
from urllib.parse import unquote, urlsplit

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode


SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
SEGMENT = re.compile(r"[A-Za-z0-9_.@+-]+")
SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
PLUGIN_NAME = re.compile(r"(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?")
RESERVED = {"con", "prn", "aux", "nul", *("com%d" % i for i in range(1, 10)),
            *("lpt%d" % i for i in range(1, 10))}
STRING_TAG = "tag:yaml.org,2002:str"
MAPPING_TAG = "tag:yaml.org,2002:map"
SEQUENCE_TAG = "tag:yaml.org,2002:seq"
FileMap = Mapping[str, Tuple[str, bytes]]


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def path_name(name):
    """Return a portable relative file path, or reject it without normalizing."""
    require(type(name) is str and name and not name.startswith("/"),
            "Invalid path")
    for part in name.split("/"):
        require(SEGMENT.fullmatch(part) and part not in {".", ".."}
                and not part.endswith(".") and part.casefold() != ".git"
                and part.split(".")[0].casefold() not in RESERVED,
                "Unsupported or unsafe filename: " + name)
    return name


def validate_files(files):
    """Copy a complete byte/mode map and reject portable path/tree ambiguity."""
    require(isinstance(files, Mapping), "Files must be a path map")
    result, spellings, used = {}, {}, set()
    for name, value in files.items():
        path_name(name)
        require(type(value) is tuple and len(value) == 2,
                "Expected a (Git mode, bytes) pair")
        mode, raw = value
        require(type(mode) is str and mode in {"100644", "100755"} and type(raw) is bytes,
                "Only captured regular Git-mode bytes are supported")
        folded = name.casefold()
        require(folded not in used, "Duplicate or case-colliding file: " + name)
        for end in range(1, len(name.split("/")) + 1):
            prefix = "/".join(name.split("/")[:end])
            prior = spellings.setdefault(prefix.casefold(), prefix)
            require(prior == prefix, "Case-colliding path component: " + prefix)
        used.add(folded)
        result[name] = value
    for name in used:
        parts = name.split("/")
        require(all("/".join(parts[:end]) not in used
                    for end in range(1, len(parts))),
                "File/directory collision: " + name)
    return MappingProxyType(result)


def inventory(files):
    return [{"path": name, "mode": mode, "bytes": len(raw),
             "sha256": hashlib.sha256(raw).hexdigest()}
            for name, (mode, raw) in sorted(files.items())]


def content_sha256(files):
    raw = (json.dumps(inventory(files), sort_keys=True, indent=2,
                      ensure_ascii=False) + "\n").encode()
    return hashlib.sha256(raw).hexdigest()


def _same_entry(left, right):
    return (left.st_dev, left.st_ino, left.st_mode) == (
        right.st_dev, right.st_ino, right.st_mode)


def _unchanged(left, right):
    return _same_entry(left, right) and (
        left.st_size, left.st_mtime_ns, left.st_ctime_ns) == (
        right.st_size, right.st_mtime_ns, right.st_ctime_ns)


def _open_absolute_directory(path):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def capture_directory(root):
    """Capture regular bytes through pinned, directory-relative no-follow reads.

    Root and internal links, empty directories, changed entries and unsupported
    modes fail. This is an observed tree, not an atomic revision or approval.
    Later staging never reopens this source.
    """
    files, _ = _capture_directory(root)
    return files


def _capture_directory(root):
    """Return captured files and the directory name from the same root binding."""
    root = Path(root)
    original = root.lstat()
    require(stat.S_ISDIR(original.st_mode), "Root must be a real directory")
    resolved = root.resolve(strict=True)
    descriptor = _open_absolute_directory(resolved)
    result = {}

    def walk(directory_fd, prefix):
        directory_before = os.fstat(directory_fd)
        names = sorted(os.listdir(directory_fd))
        require(names, "Empty directory cannot be captured: " + (prefix or "."))
        entries = {}
        for entry in names:
            name = path_name(prefix + entry)
            before = os.stat(entry, dir_fd=directory_fd, follow_symlinks=False)
            entries[entry] = before
            if stat.S_ISDIR(before.st_mode):
                child = os.open(entry, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=directory_fd)
                try:
                    require(_same_entry(before, os.fstat(child)),
                            "Directory changed during capture: " + name)
                    walk(child, name + "/")
                finally:
                    os.close(child)
            else:
                require(stat.S_ISREG(before.st_mode),
                        "Only regular files and directories are supported: " + name)
                file_fd = os.open(entry, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                  dir_fd=directory_fd)
                try:
                    opened = os.fstat(file_fd)
                    require(stat.S_ISREG(opened.st_mode)
                            and _same_entry(before, opened),
                            "File changed during capture: " + name)
                    mode = stat.S_IMODE(opened.st_mode)
                    require(mode in {0o644, 0o755},
                            "Unsupported file permissions: " + name)
                    chunks = []
                    while True:
                        chunk = os.read(file_fd, 1024 * 1024)
                        if not chunk:
                            break
                        chunks.append(chunk)
                    require(_unchanged(opened, os.fstat(file_fd)),
                            "File changed during capture: " + name)
                    result[name] = ("100755" if mode == 0o755 else "100644",
                                    b"".join(chunks))
                finally:
                    os.close(file_fd)
        require(sorted(os.listdir(directory_fd)) == names,
                "Directory entries changed during capture: " + (prefix or "."))
        for entry, before in entries.items():
            require(_unchanged(before, os.stat(entry, dir_fd=directory_fd,
                                               follow_symlinks=False)),
                    "Entry changed during capture: " + prefix + entry)
        require(_unchanged(directory_before, os.fstat(directory_fd)),
                "Directory changed during capture: " + (prefix or "."))

    try:
        require(_same_entry(original, os.fstat(descriptor)),
                "Root changed while being bound")
        walk(descriptor, "")
    finally:
        os.close(descriptor)
    return validate_files(result), resolved.name


@dataclass(frozen=True)
class Skill:
    directory: str
    name: str
    aliases: Tuple[str, ...]
    description: Optional[str] = None


@dataclass(frozen=True)
class Artifact:
    files: FileMap
    kind: str
    directory_name: Optional[str]
    package_name: Optional[str]
    skills: Tuple[Skill, ...]


@dataclass(frozen=True)
class Plan:
    files: FileMap
    correspondence: Mapping[str, str]
    layout: str
    package_name: Optional[str]
    selected_names: Tuple[str, ...]
    operational_closure: str = "not_checked"


def _yaml_mapping(node):
    require(isinstance(node, MappingNode) and node.tag == MAPPING_TAG,
            "Frontmatter must be one ordinary YAML mapping")
    result = {}
    for key, value in node.value:
        require(isinstance(key, ScalarNode) and key.tag == STRING_TAG,
                "YAML keys must be strings; merge/complex keys are unsupported")
        require(key.value not in result, "Duplicate decoded YAML key: " + key.value)
        result[key.value] = value
    return result


def _check_yaml_nodes(node, active, completed):
    if id(node) in completed:
        return
    require(id(node) not in active, "Recursive YAML aliases are unsupported")
    active.add(id(node))
    try:
        if isinstance(node, MappingNode):
            for value in _yaml_mapping(node).values():
                _check_yaml_nodes(value, active, completed)
        elif isinstance(node, SequenceNode):
            require(node.tag == SEQUENCE_TAG, "Tagged YAML collections are unsupported")
            for value in node.value:
                _check_yaml_nodes(value, active, completed)
        else:
            require(isinstance(node, ScalarNode), "Unsupported YAML node")
            require(node.tag.startswith("tag:yaml.org,2002:")
                    and node.tag.rsplit(":", 1)[1] in
                    {"str", "null", "bool", "int", "float", "timestamp", "binary"},
                    "Custom YAML tags are unsupported")
    finally:
        active.remove(id(node))
    completed.add(id(node))


def _metadata(raw):
    value = raw.decode("utf-8")
    lines = value.splitlines(keepends=True)
    require(lines and lines[0].rstrip("\r\n") == "---",
            "Missing YAML frontmatter")
    closing = next((i for i in range(1, len(lines))
                    if lines[i].rstrip("\r\n") == "---"), None)
    require(closing is not None, "Unterminated YAML frontmatter")
    try:
        node = yaml.compose("".join(lines[1:closing]), Loader=yaml.SafeLoader)
    except yaml.YAMLError as error:
        raise Invalid("Invalid YAML frontmatter: " + str(error)) from error
    values = _yaml_mapping(node)
    _check_yaml_nodes(node, set(), set())
    return values


def _skill(files, directory, folder, native):
    path = (directory + "/" if directory else "") + "SKILL.md"
    require(path in files, "Missing skill entrypoint: " + path)
    metadata = _metadata(files[path][1])
    name_node = metadata.get("name")
    require(isinstance(name_node, ScalarNode) and name_node.tag == STRING_TAG,
            "Skill name must decode as a YAML string")
    name = name_node.value
    require(1 <= len(name) <= 64 and SKILL_NAME.fullmatch(name),
            "Invalid skill invocation name: " + name)
    description = metadata.get("description")
    decoded_description = (description.value if isinstance(description, ScalarNode)
                           and description.tag == STRING_TAG else None)
    if native:
        require(name == folder, "Native skill name must match its directory")
        require(decoded_description is not None and bool(decoded_description.strip())
                and len(decoded_description) <= 1024,
                "Native skill description must be a nonempty string of at most 1024 characters")
    return Skill(directory, name, tuple(dict.fromkeys((folder, name))), decoded_description)


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key: " + key)
        result[key] = value
    return result


def _plugin(raw):
    try:
        plugin = json.loads(raw, object_pairs_hook=_unique_json)
    except (ValueError, UnicodeError) as error:
        raise Invalid("Invalid plugin JSON: " + str(error)) from error
    allowed = {"$schema", "name", "version", "description", "author", "homepage",
               "repository", "license", "keywords"}
    require(type(plugin) is dict and {"$schema", "name"} <= set(plugin)
            and set(plugin) <= allowed,
            "Unsupported plugin fields or producer profile")
    require(plugin["$schema"] == SCHEMA, "Unsupported plugin schema")
    name = plugin["name"]
    require(type(name) is str and 1 <= len(name) <= 64 and PLUGIN_NAME.fullmatch(name),
            "Invalid native package name")
    for field in ("version", "description", "homepage", "repository", "license"):
        require(field not in plugin or type(plugin[field]) is str,
                "Plugin " + field + " must be a string")
    if "author" in plugin:
        author = plugin["author"]
        require(type(author) is dict and set(author) <= {"name", "email", "url"}
                and all(type(value) is str for value in author.values()),
                "Plugin author must be an ordinary name/email/url object")
    require("keywords" not in plugin or type(plugin["keywords"]) is list
            and all(type(value) is str for value in plugin["keywords"]),
            "Plugin keywords must be a string array")
    return name


def offering_roots(paths):
    """Locate offerings in this distribution layout, before validating them.

    Immediate SKILL.md roots are standalone offerings; every observed
    systems/<name>/runtime prefix is a native offering, even without markers.
    This opt-in locator does not impose native filename rules on legacy data
    or constrain describe() callers that use another containing layout.
    """
    require(not isinstance(paths, (str, bytes)), "Expected an iterable of source paths")
    paths = tuple(paths)
    require(all(type(name) is str for name in paths), "Source paths must be strings")
    roots = {name.split("/")[0] for name in paths
             if name.count("/") == 1 and name.endswith("/SKILL.md")}
    native = {"/".join(name.split("/")[:3]) for name in paths
              if len(name.split("/")) >= 3 and name.split("/")[0] == "systems"
              and name.split("/")[2] == "runtime"}
    require(not (native and "systems" in roots), "Overlapping source artifact roots")
    roots.update(native)
    require(roots, "Source contains no skill packages")
    return tuple(sorted(roots))


def describe(files, directory_name=None):
    """Discover every entrypoint before planning a selected leaf projection.

    A standalone skill retains its directory identity. Native identity comes
    from plugin.json, so its containing directory supplies no name constraint.
    """
    files = validate_files(files)
    root_skill, plugin = "SKILL.md" in files, "plugin.json" in files
    require(root_skill != plugin, "Artifact needs exactly one root SKILL.md or plugin.json")
    if root_skill:
        path_name(directory_name)
        require("/" not in directory_name, "Artifact directory name must be one segment")
        skill = _skill(files, "", directory_name, False)
        return Artifact(files, "standalone", directory_name, None, (skill,))
    package_name = _plugin(files["plugin.json"][1])
    roots = {name.split("/")[0] for name in files}
    extension_directories = {name.split("/")[0] for name in files if "/" in name
                             and re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+",
                                              name.split("/")[0])}
    require("mcp.json" not in roots and not extension_directories,
            "Unsupported native MCP or extension component layout")
    require(all(not name.startswith("skills/") or len(name.split("/")) >= 3
                for name in files), "Native skills must be immediate child directories")
    folders = sorted({name.split("/")[1] for name in files
                      if name.startswith("skills/")})
    require(folders, "Native producer profile requires at least one skill")
    skills = tuple(_skill(files, "skills/" + folder, folder, True) for folder in folders)
    return Artifact(files, "native", None, package_name, skills)


def validate_namespace(artifacts):
    """Validate whole-distribution invocation identities, not a flat leaf merge."""
    identities, folded_identities, packages = set(), set(), set()
    for artifact in artifacts:
        if artifact.kind == "native":
            package = artifact.package_name
            require(package not in packages, "Duplicate native package name: " + package)
            packages.add(package)
            offered = {package + ":" + skill.name for skill in artifact.skills}
        else:
            require(artifact.kind == "standalone", "Unknown artifact kind")
            offered = {alias for skill in artifact.skills for alias in skill.aliases}
        local_folded = set()
        for name in offered:
            folded = name.casefold()
            require(folded not in folded_identities,
                    "Duplicate invocation identity: " + name)
            local_folded.add(folded)
            identities.add(name)
        folded_identities.update(local_folded)
    return tuple(sorted(identities))


def _check_markdown(files):
    for name, (_, raw) in files.items():
        if not name.lower().endswith(".md"):
            continue
        for target in re.findall(r"\]\(([^\s)]+)\)", raw.decode("utf-8")):
            url = urlsplit(target)
            if url.scheme or url.netloc or not url.path:
                continue
            decoded_path = unquote(url.path)
            require(not decoded_path.startswith("/"), "Absolute Markdown reference: " + name)
            parts = list(PurePosixPath(name).parent.parts)
            for part in decoded_path.split("/"):
                if part == "..":
                    require(parts, "Markdown reference escapes staged root: " + name)
                    parts.pop()
                elif part not in {"", "."}:
                    parts.append(part)
            resolved = "/".join(parts)
            require(not resolved or resolved in files
                    or any(path.startswith(resolved + "/") for path in files),
                    "Missing staged Markdown reference: " + name + " -> " + target)


def plan_intact(artifact):
    files = validate_files(artifact.files)
    _check_markdown(files)
    return Plan(files, MappingProxyType({name: name for name in files}), "intact",
                artifact.package_name, tuple(skill.name for skill in artifact.skills))


def plan_skills(artifact, selected_names=None):
    if selected_names is None:
        skills = artifact.skills
    else:
        require(not isinstance(selected_names, str), "Select an iterable of skill names")
        selections = tuple(selected_names)
        require(selections and len(set(selections)) == len(selections),
                "Select at least one skill without duplicates")
        chosen = []
        for name in selections:
            matches = [skill for skill in artifact.skills if name in skill.aliases]
            require(len(matches) == 1, "Unknown or ambiguous selected skill: " + str(name))
            require(matches[0] not in chosen, "Duplicate selected skill aliases")
            chosen.append(matches[0])
        skills = tuple(chosen)
    files, correspondence, aliases = {}, {}, set()
    for skill in skills:
        for alias in skill.aliases:
            require(alias not in aliases, "Colliding selected invocation alias: " + alias)
            aliases.add(alias)
        prefix = skill.directory + "/" if skill.directory else ""
        leaf = {name[len(prefix):]: value for name, value in artifact.files.items()
                if name.startswith(prefix)}
        _check_markdown(leaf)
        folder = PurePosixPath(skill.directory).name if skill.directory else artifact.directory_name
        for name, value in leaf.items():
            destination = folder + "/" + name
            require(destination not in files, "Duplicate selected destination")
            files[destination] = value
            correspondence[destination] = prefix + name
    require(files, "No selected skill files")
    return Plan(validate_files(files), MappingProxyType(correspondence), "skills",
                artifact.package_name, tuple(skill.name for skill in skills))


def write_new(plan, destination):
    """Write captured bytes into a fresh destination and verify the actual tree.

    Existing destinations fail without writes. Failures preserve owned residue
    for inspection; no unknown files or directories are removed.
    """
    files = validate_files(plan.files)
    require(files and set(plan.correspondence) == set(files), "Incomplete staging plan")
    require(plan.layout in {"intact", "skills"}
            and plan.operational_closure == "not_checked", "Unsupported staging plan")
    destination = Path(destination)
    parent_before = destination.parent.stat()
    destination_parent = destination.parent.resolve(strict=True)
    owned_destination = destination_parent / destination.name
    destination_parent_fd = _open_absolute_directory(destination_parent)
    created = False
    try:
        require(_same_entry(parent_before, os.fstat(destination_parent_fd)),
                "Destination parent changed while being bound")
        os.mkdir(destination.name, dir_fd=destination_parent_fd)
        created = True
        root_fd = os.open(destination.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                          dir_fd=destination_parent_fd)
        owned_root = os.fstat(root_fd)
        try:
            directories = sorted({"/".join(name.split("/")[:end]) for name in files
                                  for end in range(1, len(name.split("/")))},
                                 key=lambda name: (name.count("/"), name))
            for name in directories:
                parent_fd = os.dup(root_fd)
                try:
                    parts = name.split("/")
                    for part in parts[:-1]:
                        next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                          dir_fd=parent_fd)
                        os.close(parent_fd)
                        parent_fd = next_fd
                    os.mkdir(parts[-1], dir_fd=parent_fd)
                finally:
                    os.close(parent_fd)
            for name, (mode, raw) in sorted(files.items()):
                parent_fd = os.dup(root_fd)
                try:
                    parts = name.split("/")
                    for part in parts[:-1]:
                        next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                          dir_fd=parent_fd)
                        os.close(parent_fd)
                        parent_fd = next_fd
                    descriptor = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                         | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
                    try:
                        offset = 0
                        while offset < len(raw):
                            written = os.write(descriptor, raw[offset:])
                            require(written > 0, "Short staging write")
                            offset += written
                        os.fchmod(descriptor, 0o755 if mode == "100755" else 0o644)
                    finally:
                        os.close(descriptor)
                finally:
                    os.close(parent_fd)
        finally:
            os.close(root_fd)
        require(_same_entry(owned_root, os.stat(destination.name, dir_fd=destination_parent_fd,
                                               follow_symlinks=False))
                and _same_entry(owned_root, destination.lstat()),
                "Staging destination changed before verification")
        actual = capture_directory(destination)
        require(_same_entry(owned_root, destination.lstat()),
                "Staging destination changed during verification")
        require(actual == files, "Staged tree differs from planned bytes or modes")
        return {"layout": plan.layout, "package_name": plan.package_name,
                "selected_names": list(plan.selected_names),
                "operational_closure": "not_checked", "inventory": inventory(actual),
                "content_sha256": content_sha256(actual),
                "correspondence": dict(plan.correspondence)}
    except (Invalid, OSError, UnicodeError) as error:
        if not created:
            raise
        raise Invalid(str(error) + "; owned staging residue may remain at "
                      + str(owned_destination)) from error
    finally:
        os.close(destination_parent_fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--layout", choices=("intact", "skills"), required=True)
    parser.add_argument("--skill", action="append", dest="selected_names")
    parser.add_argument("--expected-content-sha256")
    args = parser.parse_args(argv)
    require(args.layout == "skills" or args.selected_names is None,
            "Skill selection requires the skills layout")
    # '.' and '..' are locators, not artifact names. Reuse the name obtained
    # while binding the root; resolving again could select a changed alias.
    captured, directory_name = _capture_directory(args.source)
    observed_digest = content_sha256(captured)
    require(args.expected_content_sha256 is None
            or args.expected_content_sha256 == observed_digest,
            "Captured source differs from expected content identity")
    artifact = describe(captured, directory_name)
    plan = (plan_intact(artifact) if args.layout == "intact"
            else plan_skills(artifact, args.selected_names))
    result = write_new(plan, args.destination)
    result["captured_content_sha256"] = observed_digest
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (Invalid, OSError, UnicodeError) as error:
        print("Staging blocked: " + str(error), file=sys.stderr)
        raise SystemExit(1)
