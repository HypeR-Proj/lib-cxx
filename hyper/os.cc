// SPDX-FileCopyrightText: 2026 roolrz
// SPDX-License-Identifier: Apache-2.0

#include <stdint.h>
#include <string.h>
#include <time.h>
extern "C" {
#include <hyper/syscall.h>
#include <hyper/thread.h>
#include <hyper/stream.h>
#include <hyper/std.h>
}

extern "C" [[noreturn]] void hyper_cxx_fatal(const char *message)
{
	// Runtime stream selectors are 0/1/2, not startup purpose IDs.
	size_t actual = 0;
	const char *prefix = "C++ runtime failure: ";
	hyper_runtime_stdio_write(2, prefix, strlen(prefix), &actual);
	hyper_runtime_stdio_write(2, message, strlen(message), &actual);
	hyper_runtime_stdio_write(2, "\n", 1, &actual);
	hyper_runtime_stream_fence(2);
	hyper_process_exit(1);
}

extern "C" uint64_t hyper_cxx_clock(uint32_t realtime)
{
	timespec result;
	if (clock_gettime(realtime ? CLOCK_REALTIME : CLOCK_MONOTONIC, &result))
		hyper_cxx_fatal("clock read failed");
	if (result.tv_sec < 0 || result.tv_nsec < 0 || result.tv_nsec >= 1000000000 ||
	    uint64_t(result.tv_sec) > (UINT64_MAX - result.tv_nsec) / 1000000000)
		hyper_cxx_fatal("clock outside representable range");
	return uint64_t(result.tv_sec) * 1000000000 + result.tv_nsec;
}

extern "C" void hyper_cxx_sleep(uint64_t ns)
{
	auto now = hyper_cxx_clock(0);
	auto deadline = ns >= UINT64_MAX - now ? UINT64_MAX - 1 : now + ns;
	if (hyper_thread_sleep(deadline))
		hyper_cxx_fatal("thread sleep failed");
}

extern "C" void hyper_cxx_yield()
{
	if (hyper_thread_yield())
		hyper_cxx_fatal("thread yield failed");
}
