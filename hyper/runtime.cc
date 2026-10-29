// SPDX-FileCopyrightText: 2026 roolrz
// SPDX-License-Identifier: Apache-2.0

#include <__thread/support.h>
#include <__verbose_abort>
#include <chrono>
#include <cstdlib>
#include <new>
#include <stdexcept>
#include <stdint.h>
#include <time.h>
extern "C" [[noreturn]] void hyper_cxx_fatal(const char *);

extern "C" void __cxa_pure_virtual()
{
	hyper_cxx_fatal("C++ pure virtual call");
}

// Both Native targets are little-endian. Bit zero is the ABI initialized byte;
// bit eight is private initialization ownership. Aliasing is intentional: Clang
// emits a byte acquire load while the runtime uses an aligned 32-bit futex word.
using GuardWord __attribute__((may_alias)) = uint32_t;

extern "C" int __cxa_guard_acquire(uint64_t *guard)
{
	auto *state = reinterpret_cast<GuardWord *>(guard);
	for (;;) {
		uint32_t current = __atomic_load_n(state, __ATOMIC_ACQUIRE);
		if (current == 1)
			return 0;
		if (current == 0 && __atomic_compare_exchange_n(state, &current, 256, false,
								__ATOMIC_ACQUIRE, __ATOMIC_RELAXED))
			return 1;
		hyper_runtime_wait_u32(state, 256, UINT64_MAX);
	}
}

extern "C" void __cxa_guard_release(uint64_t *guard)
{
	auto *state = reinterpret_cast<GuardWord *>(guard);
	__atomic_store_n(state, 1, __ATOMIC_RELEASE);
	hyper_runtime_wake_u32(state, UINT32_MAX);
}

extern "C" void __cxa_guard_abort(uint64_t *guard)
{
	auto *state = reinterpret_cast<GuardWord *>(guard);
	__atomic_store_n(state, 0, __ATOMIC_RELEASE);
	hyper_runtime_wake_u32(state, UINT32_MAX);
}

_LIBCPP_BEGIN_NAMESPACE_STD
[[noreturn]] void __libcpp_verbose_abort(const char *message, ...) noexcept
{
	hyper_cxx_fatal(message);
}

static uintptr_t next_id = 1;

static uintptr_t id_key()
{
	static uintptr_t key = hyper_runtime_tls_create(nullptr);
	if (!key)
		hyper_cxx_fatal("C++ TLS allocation failed");
	return key;
}

static uintptr_t allocate_id()
{
	auto id = __atomic_fetch_add(&next_id, 1, __ATOMIC_RELAXED);
	if (!id || id == UINTPTR_MAX)
		hyper_cxx_fatal("C++ thread ID exhausted");
	return id;
}

uintptr_t __libcpp_thread_get_current_id()
{
	auto key = id_key();
	auto id = reinterpret_cast<uintptr_t>(hyper_runtime_tls_get(key));
	if (!id) {
		id = allocate_id();
		hyper_runtime_tls_set(key, reinterpret_cast<void *>(id));
	}
	return id;
}

struct ThreadStart {
	void *(*fn)(void *);
	void *arg;
	uintptr_t id;
};

int __libcpp_thread_create(__libcpp_thread_t *out, void *(*fn)(void *), void *arg)
{
	auto start = new (std::nothrow) ThreadStart{fn, arg, allocate_id()};
	if (!start)
		return 12;
	auto id = start->id;
	uintptr_t token = 0;
	auto status = hyper_runtime_thread_spawn(
		256 * 1024,
		[](void *p) {
			auto *s = static_cast<ThreadStart *>(p);
			hyper_runtime_tls_set(id_key(), reinterpret_cast<void *>(s->id));
			auto fn = s->fn;
			void *arg = s->arg;
			delete s;
			fn(arg);
		},
		start, &token);
	if (status != 0) {
		delete start;
		return 11;
	}
	*out = {token, id};
	return 0;
}

namespace chrono
{
system_clock::time_point system_clock::now() noexcept
{
	auto value = hyper_cxx_clock(1);
	if (value > INT64_MAX)
		hyper_cxx_fatal("system clock outside signed nanosecond range");
	return time_point(duration_cast<duration>(nanoseconds(value)));
}

time_t system_clock::to_time_t(const time_point &t) noexcept
{
	return duration_cast<seconds>(t.time_since_epoch()).count();
}

system_clock::time_point system_clock::from_time_t(time_t t) noexcept
{
	return time_point(seconds(t));
}

steady_clock::time_point steady_clock::now() noexcept
{
	auto value = hyper_cxx_clock(0);
	if (value > INT64_MAX)
		hyper_cxx_fatal("steady clock outside signed nanosecond range");
	return time_point(duration_cast<duration>(nanoseconds(value)));
}
} // namespace chrono

_LIBCPP_END_NAMESPACE_STD
