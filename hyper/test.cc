// SPDX-FileCopyrightText: 2026 roolrz
// SPDX-License-Identifier: Apache-2.0
#include <algorithm>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <map>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <string>
#include <system_error>
#include <thread>
#include <unordered_map>
#include <vector>
extern "C" {
#include <hyper/stream.h>
#include <hyper/std.h>
}

#define CHECK(condition) do { if (!(condition)) return __LINE__; } while (0)

#ifdef HYPER_TEST_DYNAMIC_INITIALIZATION
static int startup_order;
__attribute__((constructor(200))) static void second_constructor()
{
	startup_order = startup_order == 1 && errno == 57 ? 2 : 99;
}
__attribute__((constructor(101))) static void first_constructor()
{
	errno = 57;
	startup_order = 1;
}
struct StartupProbe {
	StartupProbe() { startup_order = startup_order == 2 ? 3 : 99; }
};
static StartupProbe startup_probe;
#endif

static std::atomic<int> constructions{0};
static int initialized_once()
{
	static int value = [] { ++constructions; std::this_thread::sleep_for(std::chrono::milliseconds(2)); return 42; }();
	return value;
}

int main()
{
#ifdef HYPER_TEST_DYNAMIC_INITIALIZATION
	CHECK(startup_order == 3);
#endif
	std::vector<int> values{9, 1, 4, 4, -7};
	std::sort(values.begin(), values.end());
	CHECK(values.front() == -7 && values.back() == 9);
	std::map<std::string, int> nodes{{"file", 42}};
	std::unordered_map<std::string, int> pages;
	for (int i = 0; i != 200; ++i)
		pages.emplace("page-" + std::to_string(i), i);
	CHECK(nodes["file"] == 42 && pages["page-199"] == 199);
	CHECK(std::stoll("-42") == -42);
	CHECK(std::make_error_code(std::errc::invalid_argument).message().size() > 0);
	struct alignas(4096) Page { char bytes[4096]; };
	auto page = std::make_unique<Page>();
	CHECK(!(reinterpret_cast<uintptr_t>(page.get()) & 4095));
	std::mutex mutex;
	std::condition_variable condition;
	std::atomic<int> errors{0};
	std::atomic<int> once_count{0};
	std::once_flag once;
	int counter = 0;
	errno = EINVAL;
	std::vector<std::thread> workers;
	for (int i = 0; i != 4; ++i)
		workers.emplace_back([&, i] {
			errno = i + 100;
			if (initialized_once() != 42) ++errors;
			std::call_once(once, [&] { ++once_count; });
			for (int j = 0; j != 1000; ++j) {
				std::lock_guard lock(mutex);
				++counter;
			}
			if (errno != i + 100 || std::this_thread::get_id() == std::thread::id{}) ++errors;
		});
	for (auto &worker : workers) worker.join();
	CHECK(counter == 4000 && !errors && constructions == 1 && once_count == 1 && errno == EINVAL);
	std::unique_lock lock(mutex);
	CHECK(condition.wait_until(lock, std::chrono::system_clock::time_point{}) == std::cv_status::timeout);
	CHECK(condition.wait_for(lock, std::chrono::milliseconds(2)) == std::cv_status::timeout);
	bool ready = false;
	std::thread worker([&] {
		std::lock_guard guard(mutex);
		ready = true;
		condition.notify_one();
	});
	CHECK(condition.wait_for(lock, std::chrono::seconds(2), [&] { return ready; }));
	lock.unlock();
	worker.join();
	std::recursive_mutex recursive;
	recursive.lock();
	CHECK(recursive.try_lock());
	recursive.unlock();
	recursive.unlock();
	std::shared_mutex shared;
	shared.lock_shared();
	CHECK(!shared.try_lock());
	shared.unlock_shared();
	CHECK(shared.try_lock());
	shared.unlock();
	std::atomic<int> notification{0};
	std::thread notifier([&] { notification.store(1, std::memory_order_release); notification.notify_one(); });
	while (notification.load(std::memory_order_acquire) == 0) notification.wait(0);
	notifier.join();
	std::atomic<bool> finished{false};
	std::thread([&] { finished.store(true, std::memory_order_release); }).detach();
	while (!finished.load(std::memory_order_acquire)) std::this_thread::yield();
	size_t written;
	const char message[] = "LIBCXX-NATIVE: PASS\n";
	CHECK(!hyper_runtime_stdio_write(1, message, sizeof(message) - 1, &written));
	CHECK(written == sizeof(message) - 1);
	return 0;
}
