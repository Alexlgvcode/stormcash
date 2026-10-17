// A fixed-size thread pool for Monte Carlo replicates.
//
// Replicates share nothing: each owns its Sim, RNG and buffers, and its result
// depends only on (params, seed). So the pool only has to hand out tasks and
// return results; which thread ran a replicate never changes its numbers.
#pragma once

#include <condition_variable>
#include <functional>
#include <future>
#include <memory>
#include <mutex>
#include <queue>
#include <thread>
#include <type_traits>
#include <vector>

namespace scale {

class ThreadPool {
 public:
  explicit ThreadPool(unsigned threads) {
    if (threads == 0) threads = 1;
    for (unsigned i = 0; i < threads; ++i) workers_.emplace_back([this] { work(); });
  }

  ThreadPool(const ThreadPool&) = delete;
  ThreadPool& operator=(const ThreadPool&) = delete;

  // Finishes the queued tasks, then joins.
  ~ThreadPool() {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      stopping_ = true;
    }
    wake_.notify_all();
    for (auto& w : workers_) w.join();
  }

  // Queue `task`; the future gets its result, or the exception it threw.
  template <typename F>
  auto submit(F task) -> std::future<std::invoke_result_t<F>> {
    using R = std::invoke_result_t<F>;
    // packaged_task is move-only and std::function needs copyable, hence the shared_ptr.
    auto job = std::make_shared<std::packaged_task<R()>>(std::move(task));
    std::future<R> result = job->get_future();
    {
      std::lock_guard<std::mutex> lock(mutex_);
      queue_.emplace([job] { (*job)(); });
    }
    wake_.notify_one();
    return result;
  }

  std::size_t size() const { return workers_.size(); }

 private:
  void work() {
    for (;;) {
      std::function<void()> job;
      {
        std::unique_lock<std::mutex> lock(mutex_);
        wake_.wait(lock, [this] { return stopping_ || !queue_.empty(); });
        if (queue_.empty()) return;  // stopping, and nothing left to do
        job = std::move(queue_.front());
        queue_.pop();
      }
      job();
    }
  }

  std::vector<std::thread> workers_;
  std::queue<std::function<void()>> queue_;
  std::mutex mutex_;
  std::condition_variable wake_;
  bool stopping_ = false;
};

}  // namespace scale
