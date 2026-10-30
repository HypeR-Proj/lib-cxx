#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 roolrz
# SPDX-License-Identifier: Apache-2.0
"""Check public SDK C++ consumers, including unsupported feature rejection."""
import argparse
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent


def check(workspace):
    workspace = workspace.resolve()
    linker = subprocess.check_output(
        ["sh", str(workspace / "scripts/find-llvm-tool.sh"), "ld.lld"], text=True
    ).strip()
    compiler = os.environ.get("HYPER_CXX", os.environ.get("CLANG", "clang++"))
    for arch in ("aarch64", "riscv64"):
        subprocess.run(["make", "sdk", f"ARCH={arch}"], cwd=workspace, check=True)
        sdk, output = (
            workspace / f"target/sdk/{arch}",
            workspace / f"target/lib-cxx-test/{arch}",
        )
        output.mkdir(parents=True, exist_ok=True)
        environment = {
            **os.environ,
            "HYPER_SYSROOT": str(sdk),
            "HYPER_LD": linker,
            "HYPER_CXX": compiler,
        }
        for optimization in ("0", "2"):
            for mode in ("static", "dynamic"):
                subprocess.run(
                    [
                        str(sdk / "bin/hyper-clang++"),
                        "-O" + optimization,
                        *(
                            ["-DHYPER_TEST_DYNAMIC_INITIALIZATION=1"]
                            if mode == "dynamic"
                            else []
                        ),
                        str(HERE / "test.cc"),
                        "-Wl,-z,stack-size=524288",
                        "-o",
                        str(output / f"{mode}-O{optimization}"),
                    ],
                    env={**environment, "HYPER_LINK_MODE": mode},
                    check=True,
                )
        for name, source, flags, diagnostic in (
            (
                "exceptions",
                "#include <vector>\nint main() { return 0; }\n",
                ["-fexceptions"],
                "requires -fno-exceptions",
            ),
            (
                "rtti",
                "#include <vector>\nint main() { return 0; }\n",
                ["-frtti"],
                "requires -fno-exceptions",
            ),
            (
                "future",
                "#include <future>\nint main() { std::promise<int> value; value.set_value(1); }\n",
                [],
                "undefined symbol",
            ),
            (
                "destruction",
                '#include <string>\nstd::string global("x"); int main() { return global.empty(); }\n',
                [],
                "__cxa_atexit",
            ),
            (
                "initialization",
                "int value; struct Global { Global() { value = 7; } }; Global global; int main() { return value; }\n",
                ["-static"],
                "do not support dynamic global initialization",
            ),
            (
                "preinitialization",
                'void before() {}\n__attribute__((section(".preinit_array"), used)) void (*hook)() = before;\nint main() { return 0; }\n',
                [],
                "do not support pre-initialization arrays",
            ),
            (
                "finalization",
                "__attribute__((destructor)) void after() {}\nint main() { return 0; }\n",
                [],
                "do not support finalizers",
            ),
            (
                "tls",
                "thread_local int value; int main() { return ++value; }\n",
                [],
                "thread-local storage",
            ),
        ):
            rejected = output / (name + ".cc")
            rejected.write_text(source)
            result = subprocess.run(
                [
                    str(sdk / "bin/hyper-clang++"),
                    str(rejected),
                    *flags,
                    "-o",
                    str(output / name),
                ],
                env=environment,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 or diagnostic not in result.stderr:
                raise RuntimeError(
                    f"unsupported {name} did not produce its expected rejection: {result.stderr}"
                )
        print(
            f"libc++ {arch}: O0/O2 static/dynamic links and unsupported features passed",
            flush=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    check(parser.parse_args().workspace)
