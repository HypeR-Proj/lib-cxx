#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 roolrz
# SPDX-License-Identifier: Apache-2.0
"""Build libc++ for the Native SDK using the shared musl C subset."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCES = """algorithm atomic call_once condition_variable condition_variable_destructor
error_category exception functional hash memory mutex mutex_destructor new new_handler new_helpers
optional shared_mutex stdexcept string system_error thread typeinfo vector""".split()


def build(sdk, output, install=False, jobs=4):
    sdk, output = sdk.resolve(), output.resolve()
    identity = dict(
        line.split("=", 1)
        for line in (sdk / "share/hyper/manifest").read_text().splitlines()
        if "=" in line
    )
    arch = identity["architecture"]
    if arch not in ("aarch64", "riscv64"):
        raise ValueError("libc++ port supports AArch64 and RISC-V Native only")
    if not (sdk / "lib/libc.a").is_file():
        raise ValueError("install the HypeR musl port into the SDK first")
    output.mkdir(parents=True, exist_ok=True)
    compiler = os.environ.get("HYPER_CXX", "clang++")
    flags = [
        compiler,
        f"--target={arch}-none-elf",
        "-std=c++20",
        "-D_GNU_SOURCE=1",
        "-D__HYPER__=1",
        "-g",
        "-O2",
        "-fno-exceptions",
        "-fno-rtti",
        "-fno-c++-static-destructors",
        "-ffunction-sections",
        "-fdata-sections",
        "-fPIC",
        "-nostdinc++",
        "-ffreestanding",
        "-fno-stack-protector",
    ]
    if arch == "riscv64":
        flags += ["-march=rv64gc", "-mabi=lp64d", "-mno-relax"]
    includes = [ROOT / "hyper/include", ROOT / "include", sdk / "include"]
    flags += [arg for path in includes for arg in ("-I", str(path))]
    files = [ROOT / "src" / (name + ".cpp") for name in SOURCES]
    files += [ROOT / "hyper/runtime.cc", ROOT / "hyper/os.cc"]
    sys.path.insert(0, str(sdk / "share/hyper"))
    from native_library import build_archive
    archive = build_archive(ROOT, sdk, output, "libc++.a", flags, files,
                            includes + [ROOT / "src/include", ROOT / "src/support"], jobs=jobs,
                            extra=lambda source: ["-D_LIBCPP_BUILDING_LIBRARY"] if source.suffix == ".cpp" else [])
    if install:
        shutil.copytree(ROOT / "include", sdk / "include/c++/v1", dirs_exist_ok=True)
        shutil.copytree(
            ROOT / "hyper/include", sdk / "include/c++/v1", dirs_exist_ok=True
        )
        shutil.copyfile(archive, sdk / "lib/libc++.a")
        licenses = sdk / "share/licenses/libcxx"
        licenses.mkdir(parents=True, exist_ok=True)
        for name in ("LICENSE.TXT", "LICENSE-HypeR", "UPSTREAM.json"):
            shutil.copyfile(ROOT / name, licenses / name)
    (output / "compile.json").write_text(
        json.dumps({"flags": flags, "archive": str(archive)}, indent=2) + "\n"
    )
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    build(args.sdk, args.output, args.install)
