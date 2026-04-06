// Zaya OS Kernel — GPU Scheduler v4 Priority
// Selects next job from queue sorted by priority (1=CRITICAL, 2=NORMAL, 3=LOW)
// then filtered by VRAM availability. Jobs without priority default to 2.
//
// Usage: gpu_scheduler_v4_priority
// Reads:  /opt/zaya_os/hub/core/state/gpu_queue.json
// Output: JSON to stdout { "ok": true/false, "job": {...}, "vram_free": N, "priority": N }

#include "zaya/kjson.hpp"
#include <cstdio>
#include <cstdlib>
#include <array>
#include <memory>
#include <algorithm>
#include <iostream>

static const char* QUEUE_FILE = "/opt/zaya_os/hub/core/state/gpu_queue.json";

static int query_vram_free() {
    std::array<char, 256> buf;
    std::string result;

    std::unique_ptr<FILE, decltype(&pclose)> pipe(
        popen("nvidia-smi --query-gpu=memory.total,memory.used --format=csv,noheader,nounits", "r"),
        pclose
    );

    if (!pipe) return 0;

    while (fgets(buf.data(), buf.size(), pipe.get()))
        result += buf.data();

    // Parse "12288, 2048"
    auto comma = result.find(',');
    if (comma == std::string::npos) return 0;

    int total = std::stoi(result.substr(0, comma));
    int used  = std::stoi(result.substr(comma + 1));

    return total - used;
}

int main() {
    using namespace zaya;

    // Load queue
    JVal root = json_load_file(QUEUE_FILE);
    if (!root.is_object() || !root.has("queue") || !root["queue"].is_array()) {
        std::cout << json_dump(JObject{{"ok", true}, {"job", std::string("none")}}) << std::endl;
        return 0;
    }

    JArray& queue = root.obj()["queue"].arr();

    if (queue.empty()) {
        std::cout << json_dump(JObject{{"ok", true}, {"job", std::string("none")}}) << std::endl;
        return 0;
    }

    int free_vram = query_vram_free();

    // Build index sorted by priority (1 first, 3 last)
    std::vector<size_t> indices(queue.size());
    for (size_t i = 0; i < queue.size(); i++) indices[i] = i;

    std::stable_sort(indices.begin(), indices.end(), [&](size_t a, size_t b) {
        int pa = 2, pb = 2; // default NORMAL
        if (queue[a].is_object() && queue[a].has("priority") && queue[a]["priority"].is_number())
            pa = queue[a]["priority"].integer();
        if (queue[b].is_object() && queue[b].has("priority") && queue[b]["priority"].is_number())
            pb = queue[b]["priority"].integer();
        return pa < pb;
    });

    // Find first job that fits in VRAM
    for (size_t idx : indices) {
        JVal& job = queue[idx];
        if (!job.is_object()) continue;

        int required = 0;
        if (job.has("vram_required") && job["vram_required"].is_number())
            required = job["vram_required"].integer();

        if (free_vram >= required) {
            // Extract job
            JVal selected = job;
            queue.erase(queue.begin() + static_cast<long>(idx));

            // Save updated queue
            json_save_file(QUEUE_FILE, root);

            // Determine priority
            int priority = 2;
            if (selected.is_object() && selected.has("priority") && selected["priority"].is_number())
                priority = selected["priority"].integer();

            // Output
            JObject out;
            out["ok"]       = true;
            out["job"]      = selected;
            out["vram_free"] = static_cast<double>(free_vram);
            out["priority"] = static_cast<double>(priority);

            std::cout << json_dump(out) << std::endl;
            return 0;
        }
    }

    // No job fits
    JObject out;
    out["ok"]       = false;
    out["reason"]   = std::string("no_job_fits_vram");
    out["vram_free"] = static_cast<double>(free_vram);

    std::cout << json_dump(out) << std::endl;
    return 0;
}
