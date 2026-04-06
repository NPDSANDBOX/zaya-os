// Zaya OS Kernel — Checkpoint Manager v1
// Fault tolerance for multi-step pipelines. Resume from last checkpoint on crash.
//
// Usage:
//   checkpoint_manager_v1 list                          — list all checkpoints
//   checkpoint_manager_v1 inspect <job_id>              — show checkpoint state
//   checkpoint_manager_v1 reset <job_id>                — force restart from zero
//   checkpoint_manager_v1 save <job_id> <step> [json]   — mark step completed
//   checkpoint_manager_v1 query <job_id> <step>         — check if step done (exit 0=done, 1=not)
//   checkpoint_manager_v1 complete <job_id>             — mark job completed
//   checkpoint_manager_v1 fail <job_id> <error_msg>     — mark job failed (preserves progress)
//   checkpoint_manager_v1 total <job_id> <N>            — set total steps
//
// Checkpoint files: /opt/zaya_os/hub/data/contracts/checkpoints/<job_id>.ckpt.json
//
// Pipelines call via subprocess or integrate via the C++ API below.

#include "zaya/kjson.hpp"
#include <iostream>
#include <filesystem>
#include <chrono>
#include <cstring>

namespace fs = std::filesystem;

static const char* CHECKPOINT_DIR = "/opt/zaya_os/hub/data/contracts/checkpoints";

static std::string now_iso() {
    auto tp = std::chrono::system_clock::now();
    auto tt = std::chrono::system_clock::to_time_t(tp);
    char buf[64];
    std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", std::gmtime(&tt));
    return buf;
}

static std::string ckpt_path(const std::string& job_id) {
    return std::string(CHECKPOINT_DIR) + "/" + job_id + ".ckpt.json";
}

static zaya::JVal load_checkpoint(const std::string& job_id) {
    using namespace zaya;
    fs::create_directories(CHECKPOINT_DIR);
    std::string path = ckpt_path(job_id);

    if (!fs::exists(path))
        return JObject{};

    JVal state = json_load_file(path);
    if (!state.is_object())
        return JObject{};

    // If already completed, return empty (start fresh)
    if (state.has("status") && state["status"].is_string() && state["status"].str() == "completed")
        return JObject{};

    return state;
}

static void save_checkpoint(const std::string& job_id, const zaya::JVal& state) {
    fs::create_directories(CHECKPOINT_DIR);
    zaya::json_save_file(ckpt_path(job_id), state);
}

// ─── Commands ───────────────────────────────────────────

static int cmd_list() {
    using namespace zaya;
    fs::create_directories(CHECKPOINT_DIR);

    bool found = false;
    for (const auto& entry : fs::directory_iterator(CHECKPOINT_DIR)) {
        if (entry.path().extension() != ".json") continue;
        std::string fname = entry.path().filename().string();
        if (fname.find(".ckpt.json") == std::string::npos) continue;

        JVal state = json_load_file(entry.path().string());
        if (!state.is_object()) continue;

        std::string jid = state.has("job_id") ? state["job_id"].str() : "?";
        int last = state.has("last_step") ? state["last_step"].integer() : -1;
        std::string total = state.has("total_steps") && state["total_steps"].is_number()
            ? std::to_string(state["total_steps"].integer()) : "?";
        std::string status = state.has("status") ? state["status"].str() : "unknown";

        std::cout << "  " << jid << ": step " << (last + 1)
                  << "/" << total << " [" << status << "]" << std::endl;
        found = true;
    }

    if (!found)
        std::cout << "No checkpoints found" << std::endl;

    return 0;
}

static int cmd_inspect(const std::string& job_id) {
    using namespace zaya;
    std::string path = ckpt_path(job_id);

    if (!fs::exists(path)) {
        std::cout << "No checkpoint for: " << job_id << std::endl;
        return 1;
    }

    JVal state = json_load_file(path);
    std::cout << json_dump(state, 2) << std::endl;
    return 0;
}

static int cmd_reset(const std::string& job_id) {
    std::string path = ckpt_path(job_id);
    if (fs::exists(path)) {
        fs::remove(path);
    }
    std::cout << "[CHECKPOINT] Job " << job_id << " reset" << std::endl;
    return 0;
}

static int cmd_save(const std::string& job_id, int step, const std::string& data_json) {
    using namespace zaya;

    JVal state = load_checkpoint(job_id);
    JObject& s = state.obj();

    // Initialize if new
    if (!state.has("job_id")) {
        s["job_id"] = job_id;
        s["status"] = std::string("running");
        s["last_step"] = -1.0;
        s["total_steps"] = nullptr;
        s["steps"] = JObject{};
        s["started_at"] = now_iso();
    }

    // Parse step data
    JVal step_data = data_json.empty() ? JVal(JObject{}) : json_parse(data_json);

    // Save step
    JObject step_entry;
    step_entry["completed_at"] = now_iso();
    step_entry["data"] = step_data;

    s["steps"].obj()[std::to_string(step)] = step_entry;
    s["last_step"] = static_cast<double>(step);
    s["status"] = std::string("running");

    save_checkpoint(job_id, state);

    // Progress output
    if (state.has("total_steps") && state["total_steps"].is_number()) {
        int total = state["total_steps"].integer();
        std::cout << "[CHECKPOINT] Step " << (step + 1) << "/" << total << " saved" << std::endl;
    } else {
        std::cout << "[CHECKPOINT] Step " << (step + 1) << " saved" << std::endl;
    }

    return 0;
}

static int cmd_query(const std::string& job_id, int step) {
    using namespace zaya;

    JVal state = load_checkpoint(job_id);
    if (!state.is_object() || !state.has("steps"))
        return 1; // not done

    const auto& steps = state["steps"].obj();
    std::string key = std::to_string(step);

    if (steps.count(key) > 0) {
        // Step already done — output its data
        const auto& entry = steps.at(key);
        if (entry.is_object() && entry.has("data")) {
            std::cout << json_dump(entry["data"]) << std::endl;
        }
        return 0; // done → skip this step
    }

    return 1; // not done → execute this step
}

static int cmd_complete(const std::string& job_id) {
    using namespace zaya;

    JVal state = load_checkpoint(job_id);
    if (state.obj().empty()) {
        // Create minimal state
        state = JObject{{"job_id", job_id}};
    }

    state.obj()["status"] = std::string("completed");
    state.obj()["completed_at"] = now_iso();

    save_checkpoint(job_id, state);
    std::cout << "[CHECKPOINT] Job " << job_id << " completed" << std::endl;
    return 0;
}

static int cmd_fail(const std::string& job_id, const std::string& error_msg) {
    using namespace zaya;

    JVal state = load_checkpoint(job_id);
    if (state.obj().empty()) {
        state = JObject{{"job_id", job_id}, {"last_step", -1.0}, {"steps", JObject{}}};
    }

    state.obj()["status"] = std::string("failed");
    state.obj()["failed_at"] = now_iso();
    state.obj()["error"] = error_msg;

    save_checkpoint(job_id, state);

    int last = state.has("last_step") ? state["last_step"].integer() : -1;
    std::cout << "[CHECKPOINT] Job " << job_id << " failed at step "
              << (last + 1) << ": " << error_msg << std::endl;
    return 0;
}

static int cmd_total(const std::string& job_id, int total) {
    using namespace zaya;

    JVal state = load_checkpoint(job_id);
    if (state.obj().empty()) {
        state = JObject{
            {"job_id", job_id},
            {"status", std::string("running")},
            {"last_step", -1.0},
            {"steps", JObject{}},
            {"started_at", now_iso()}
        };
    }

    state.obj()["total_steps"] = static_cast<double>(total);
    save_checkpoint(job_id, state);

    std::cout << "[CHECKPOINT] Total steps set to " << total << " for " << job_id << std::endl;
    return 0;
}

// ─── Main ───────────────────────────────────────────────

int main(int argc, char* argv[]) {
    if (argc < 2) {
        std::cout << "Zaya OS Checkpoint Manager v1 (C++)\n\n"
                  << "Commands:\n"
                  << "  list                          — list all checkpoints\n"
                  << "  inspect <job_id>              — show checkpoint state\n"
                  << "  reset <job_id>                �� force restart from zero\n"
                  << "  save <job_id> <step> [json]   — mark step completed\n"
                  << "  query <job_id> <step>         — exit 0=done, 1=not done\n"
                  << "  complete <job_id>             — mark job completed\n"
                  << "  fail <job_id> <error_msg>     — mark job failed\n"
                  << "  total <job_id> <N>            — set total steps\n";
        return 0;
    }

    std::string cmd = argv[1];

    if (cmd == "list")
        return cmd_list();

    if (argc < 3) {
        std::cerr << "Missing job_id" << std::endl;
        return 1;
    }

    std::string job_id = argv[2];

    if (cmd == "inspect")
        return cmd_inspect(job_id);

    if (cmd == "reset")
        return cmd_reset(job_id);

    if (cmd == "complete")
        return cmd_complete(job_id);

    if (cmd == "save" && argc >= 4) {
        int step = std::stoi(argv[3]);
        std::string data = argc >= 5 ? argv[4] : "";
        return cmd_save(job_id, step, data);
    }

    if (cmd == "query" && argc >= 4) {
        int step = std::stoi(argv[3]);
        return cmd_query(job_id, step);
    }

    if (cmd == "fail" && argc >= 4) {
        std::string err = argv[3];
        return cmd_fail(job_id, err);
    }

    if (cmd == "total" && argc >= 4) {
        int n = std::stoi(argv[3]);
        return cmd_total(job_id, n);
    }

    std::cerr << "Unknown command: " << cmd << std::endl;
    return 1;
}
