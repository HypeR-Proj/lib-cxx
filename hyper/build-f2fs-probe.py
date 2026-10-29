#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 roolrz
# SPDX-License-Identifier: Apache-2.0
"""Build the preserved Fuchsia F2FS RAM probe using only public SDK libraries.

This optional acceptance fixture takes a checkout of the earlier F2FS port.
It regenerates media sources from verified archives and that checkout's patch;
it never consumes its private C++ runtime or previously expanded source cache.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess


def build(args):
    source, sdk, output = (
        args.source.resolve(),
        args.sdk.resolve(),
        args.output.resolve(),
    )
    if (
        output == source
        or source.is_relative_to(output)
        or sdk.is_relative_to(output)
        or output.is_relative_to(sdk)
    ):
        raise ValueError("output must not contain the source checkout or SDK")
    marker = output / ".hyper-f2fs-probe"
    if output.exists() and any(output.iterdir()) and not marker.is_file():
        raise ValueError(
            "refusing to replace an output directory not owned by this fixture"
        )
    output.mkdir(parents=True, exist_ok=True)
    marker.write_text("HypeR public-SDK F2FS acceptance fixture\n")
    spec = importlib.util.spec_from_file_location(
        "source_archive", source / "scripts/source_archive.py"
    )
    archive = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(archive)
    media = source / "lib/fs-f2fs"
    cache = args.cache.resolve() if args.cache else output / "archives"
    inputs = archive.sources(media / "sources.json", cache, args.fetch)
    tree = output / "source"
    shutil.rmtree(tree, ignore_errors=True)
    for name, directory in inputs.items():
        shutil.copytree(directory, tree / name, dirs_exist_ok=True)
    subprocess.run(
        ["patch", "-p1", "--batch", "-i", str(media / "fuchsia.patch")],
        cwd=tree,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    shutil.copytree(media / "cpp", tree, dirs_exist_ok=True)
    includes = [
        "",
        "zircon/system/public",
        "sdk/lib/zircon-assert",
        "zircon/system/ulib/fbl/include",
        "zircon/system/ulib/zx/include",
        "zircon/system/ulib/zircon-internal/include",
        "zircon/third_party/ulib/safemath/include",
        "sdk/lib/fit/include",
        "sdk/lib/fit-promise/include",
        "sdk/lib/stdcompat/include",
        "zircon/system/ulib/bitmap/include",
    ]
    excluded = {
        "bcache",
        "component_runner",
        "inspect",
        "memory_watcher",
        "vmo_manager",
        "fsck",
    }
    files = [
        path
        for path in (tree / "src/storage/f2fs").glob("*.cc")
        if path.stem not in excluded
    ]
    files += list((tree / "sdk/lib/fit-promise").glob("*.cc"))
    files += [
        tree / name
        for name in [
            "src/storage/f2fs/third_party/ext2_hash/hash.cc",
            "bridge.cc",
            "src/storage/lib/vfs/cpp/journal/background_executor.cc",
            "src/storage/lib/vfs/cpp/transaction/buffered_operations_builder.cc",
            "zircon/system/ulib/bitmap/raw-bitmap.cc",
            "zircon/system/ulib/fbl/alloc_checker.cc",
            "src/storage/lib/buffer/block_buffer.cc",
        ]
    ]
    # The preserved F2FS adapter explicitly closes mounts and joins its executor;
    # it was designed without static destruction. This is a consumer option,
    # not a silent default in the public C++ application driver.
    flags = [
        str(sdk / "bin/hyper-clang++"),
        "-O1",
        "-g",
        "-D_GNU_SOURCE=1",
        "-DHYPER_F2FS_NATIVE=1",
        "-fno-c++-static-destructors",
        "-c",
    ]
    flags += [argument for name in includes for argument in ("-I", str(tree / name))]
    environment = {
        **os.environ,
        "HYPER_SYSROOT": str(sdk),
        "CARGO_TARGET_DIR": str(output / "cargo"),
    }
    objects = output / "objects"
    objects.mkdir(exist_ok=True)

    def compile_source(path):
        obj = objects / (str(path.relative_to(tree)).replace("/", "_") + ".o")
        subprocess.run(flags + [str(path), "-o", str(obj)], env=environment, check=True)
        return str(obj)

    with ThreadPoolExecutor(max_workers=4) as pool:
        built = list(pool.map(compile_source, files))
    library = output / "libhyper-f2fs.a"
    library.unlink(missing_ok=True)
    subprocess.run(
        [os.environ.get("LLVM_AR", "llvm-ar"), "rcs", str(library)] + built, check=True
    )
    adapter = output / "fs-f2fs"
    shutil.copytree(media / "src", adapter / "src", dirs_exist_ok=True)
    (adapter / "Cargo.toml").write_text(
        '[package]\nname="hyper-fs-f2fs"\nversion="0.0.0"\nedition="2024"\n'
        'license="Apache-2.0"\npublish=false\n[dependencies]\n'
        'hyper-os={version="=0.0.0",features=["std"]}\n'
    )
    (adapter / "build.rs").write_text(
        "fn main() {\n"
        '  println!("cargo:rerun-if-changed=../libhyper-f2fs.a");\n'
        '  let output = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap();\n'
        '  println!("cargo:rustc-link-search=native={}", output.display());\n'
        '  println!("cargo:rustc-link-search=native={}/lib", std::env::var("HYPER_SYSROOT").unwrap());\n'
        '  println!("cargo:rustc-link-lib=static=hyper-f2fs");\n'
        '  println!("cargo:rustc-link-lib=static=c++");\n'
        '  println!("cargo:rustc-link-lib=static=c");\n'
        "}\n"
    )
    probe = output / "probe"
    shutil.copytree(
        source / "tests/native/f2fs-smoke/src", probe / "src", dirs_exist_ok=True
    )
    manifest = (source / "tests/native/f2fs-smoke/Cargo.toml").read_text()
    manifest = manifest.replace("../../../lib/fs-f2fs", "../fs-f2fs")
    (probe / "Cargo.toml").write_text(manifest)
    subprocess.run(
        [
            str(sdk / "bin/hyper-cargo"),
            "build",
            "--manifest-path",
            str(probe / "Cargo.toml"),
            "--release",
        ]
        + ([] if args.fetch else ["--offline"]),
        env={**environment, "HYPER_RUST_STD": "1"},
        check=True,
    )
    identity = dict(
        line.split("=", 1)
        for line in (sdk / "share/hyper/manifest").read_text().splitlines()
        if "=" in line
    )
    binary = output / "cargo" / identity["rust-std-target"] / "release/hyper-f2fs-smoke"
    receipt = {
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True
        ).strip(),
        "source_dirty": bool(
            subprocess.check_output(
                [
                    "git",
                    "status",
                    "--porcelain",
                    "--",
                    "lib/fs-f2fs",
                    "scripts/source_archive.py",
                    "tests/native/f2fs-smoke",
                ],
                cwd=source,
                text=True,
            )
        ),
        "fuchsia_patch_sha256": hashlib.sha256(
            (media / "fuchsia.patch").read_bytes()
        ).hexdigest(),
        "sdk": identity,
        "sdk_libraries": {
            name: hashlib.sha256((sdk / "lib" / name).read_bytes()).hexdigest()
            for name in ("libc.a", "libc++.a", "libhyper.so", "libcompiler-builtins.a")
        },
        "binary": str(binary),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "run_inside_hyper": "/bin/f2fs-sdk-smoke ram",
    }
    (output / "probe.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--sdk", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--fetch", action="store_true")
    build(parser.parse_args())
