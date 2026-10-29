<!-- SPDX-FileCopyrightText: 2026 roolrz -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# libc++ for HypeR Native

This is a source fork of LLVM libc++ 21.1.8 under
[Apache-2.0 with the LLVM exception](LICENSE.TXT).
[UPSTREAM.json](UPSTREAM.json) records the imported archive. The complete upstream
source and test tree is retained. Native adapters live in `hyper/`; builds select
the supported source files explicitly and never download an implementation.

The SDK installs `include/c++/v1` and `libc++.a`. The port supports the C++20
containers and algorithms used by Fuchsia F2FS, strings and integer conversions,
smart pointers, atomics, mutexes, recursive/shared mutexes, condition variables,
threads, `call_once`, function-local initialization guards, error categories and
system/steady clocks. Native runtime TLS keys provide thread cleanup; all heap
allocation uses the same Native allocator as Rust and C. The C dependency is
the public [musl port](https://github.com/HypeR-Proj/lib-musl).

## Supported boundary

Exceptions, RTTI, exception pointers, futures/async, localization, iostreams,
filesystem, timezone data, `random_device`, floating-point string conversion,
compiler-native `thread_local` and automatic static destruction are unsupported.
Unsupported APIs have no runtime implementation; applications fail to compile
or link. Exception and RTTI flags are rejected by the installed configuration.
Ordinary automatic object destruction and Native thread TLS cleanup work.
Libraries are built without static destruction for process-lifetime internal
objects; the application driver does not suppress application destruction.

With exceptions disabled, operations that require throwing terminate the
process, as configured by upstream libc++. `thread::hardware_concurrency()`
returns the standard's permitted unknown value, 0. Threads must be joined or
detached normally. Clock readings must fit the signed nanosecond representation.
Standard C/C++ shared objects are outside the initial port.
ELF pre-initialization arrays and finalizers are rejected because the Native
runtime does not implement their lifetime contracts.
Static executables also reject dynamic global initialization; dynamic Native
executables use the existing loader's constructor support.

## Build and use

```sh
make sdk ARCH=aarch64
target/sdk/aarch64/bin/hyper-clang++ example.cc -o example
python3 project.py test lib-cxx
```

The driver selects C++20, the installed headers and archives, and the standard
`main` entry point. Use `-c` to produce objects for a Rust FFI consumer; link
`c++`, `c` and the SDK's `compiler-builtins` archives through the Native driver.
Only C-compatible types and ownership contracts should cross that FFI boundary.
The compiler builtins are provided by the already selected Rust toolchain,
whose MIT/Apache notices are included in the SDK.

The Native probe exercises containers, aligned allocation, thread-local errno,
concurrent initialization and locking, timed waits, notification, thread join
and detach. Both AArch64 and RISC-V are checked at O0 and O2, including static
and dynamic Native executables. Fuchsia F2FS is an integration consumer; this
library has no dependency on filesystem code.

The host compiler must meet upstream libc++'s requirement: Clang 19 or later
(AppleClang 15 or later on macOS; use upstream LLVM for RISC-V cross compilation).

The optional [F2FS consumer builder](hyper/build-f2fs-probe.py) accepts a checkout
of the preserved F2FS port (`c8ba1d4048827da6fcd679a04c7ff903c44bb940`). It
regenerates patched sources from verified archives, builds the media core with
`hyper-clang++`, and links the existing Rust RAM probe against the public SDK:

```sh
python3 stdlib/cxx/hyper/build-f2fs-probe.py --source /path/to/f2fs-checkout \
  --sdk target/sdk/aarch64 --output target/f2fs-public-sdk --fetch
```

Install the emitted probe in a disposable HypeR image as `/bin/f2fs-sdk-smoke`
and run `/bin/f2fs-sdk-smoke ram`. It formats an owned RAM device, writes and
checks 4 MiB, synchronizes, closes/remounts, renames, and checks truncate/regrow
zeroing. The fixture does not change production filesystem selection. A normal
library build never fetches or compiles F2FS.

Full disk-worker acceptance also needs the preserved port's Rust filesystem
client fixes for remote recursive directory removal. Those remain with that
port; the RAM probe above isolates the C++ media core and its standard libraries.
