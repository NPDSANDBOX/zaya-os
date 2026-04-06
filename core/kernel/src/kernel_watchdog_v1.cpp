// Zaya OS Kernel — Watchdog v1
// Monitors registered processes. Detects hangs/crashes. Auto-restarts.
//
// Usage:
//   kernel_watchdog_v1 register <name> --cmd '<cmd>' [--health <url>] [--pattern '<grep>']
//                     [--max-restarts N] [--cooldown N]
//   kernel_watchdog_v1 unregister <name>
//   kernel_watchdog_v1 status
//   kernel_watchdog_v1 run                — start watchdog daemon loop
//
// Registry: /opt/zaya_os/hub/core/state/watchdog/registry.json
// Logs:     /opt/zaya_os/hub/core/logs/watchdog.jsonl

#include "zaya/kjson.hpp"
#include <iostream>
#include <filesystem>
#include <chrono>
#include <thread>
#include <cstring>
#include <cstdio>
#include <array>

// POSIX
#include <signal.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <fcntl.h>

namespace fs = std::filesystem;

static const char* WATCHDOG_DIR   = "/opt/zaya_os/hub/core/state/watchdog";
static const char* REGISTRY_FILE  = "/opt/zaya_os/hub/core/state/watchdog/registry.json";
static const char* LOG_FILE       = "/opt/zaya_os/hub/core/logs/watchdog.jsonl";
static constexpr int CHECK_INTERVAL = 15; // seconds
static constexpr int HEALTH_TIMEOUT = 5;  // seconds
static constexpr int DEFAULT_MAX_RESTARTS = 3;
static constexpr int DEFAULT_COOLDOWN = 30;

// ─── Utilities ──────────────────────────────────────────

static std::string now_iso() {
    auto tp = std::chrono::system_clock::now();
    auto tt = std::chrono::system_clock::to_time_t(tp);
    char buf[64];
    std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", std::gmtime(&tt));
    return buf;
}

static double now_epoch() {
    auto tp = std::chrono::system_clock::now();
    return std::chrono::duration<double>(tp.time_since_epoch()).count();
}

static void log_event(const std::string& event, const std::string& name = "",
                      const zaya::JObject& extra = {}) {
    using namespace zaya;
    JObject entry;
    entry["ts"] = now_iso();
    entry["event"] = event;
    if (!name.empty()) entry["process"] = name;
    for (const auto& [k, v] : extra) entry[k] = v;

    std::string line = json_dump(entry) + "\n";

    fs::create_directories(fs::path(LOG_FILE).parent_path());
    std::ofstream f(LOG_FILE, std::ios::app);
    f << line;

    std::cout << line << std::flush;
}

static zaya::JVal load_registry() {
    using namespace zaya;
    fs::create_directories(WATCHDOG_DIR);
    if (!fs::exists(REGISTRY_FILE)) return JObject{};
    JVal v = json_load_file(REGISTRY_FILE);
    return v.is_object() ? v : JVal(JObject{});
}

static void save_registry(const zaya::JVal& reg) {
    fs::create_directories(WATCHDOG_DIR);
    zaya::json_save_file(REGISTRY_FILE, reg);
}

static bool pid_alive(int pid) {
    if (pid <= 0) return false;
    return kill(static_cast<pid_t>(pid), 0) == 0;
}

static std::string exec_cmd(const std::string& cmd) {
    std::array<char, 4096> buf;
    std::string result;
    std::unique_ptr<FILE, decltype(&pclose)> pipe(popen(cmd.c_str(), "r"), pclose);
    if (!pipe) return "";
    while (fgets(buf.data(), buf.size(), pipe.get()))
        result += buf.data();
    return result;
}

static int find_pid_by_pattern(const std::string& pattern) {
    std::string out = exec_cmd("pgrep -f '" + pattern + "' 2>/dev/null");
    int my_pid = getpid();
    int my_ppid = getppid();

    // Parse pids, skip self
    std::istringstream ss(out);
    std::string line;
    while (std::getline(ss, line)) {
        if (line.empty()) continue;
        int pid = std::stoi(line);
        if (pid != my_pid && pid != my_ppid)
            return pid;
    }
    return 0;
}

static bool health_check(const std::string& url) {
    // Use curl with timeout — available on any Linux
    std::string cmd = "curl -sf --max-time " + std::to_string(HEALTH_TIMEOUT)
                    + " -o /dev/null -w '%{http_code}' '" + url + "' 2>/dev/null";
    std::string result = exec_cmd(cmd);

    // Check for 2xx status
    if (result.size() >= 3) {
        int code = std::stoi(result.substr(0, 3));
        return code >= 200 && code < 300;
    }
    return false;
}

static void kill_process(int pid, const std::string& name) {
    if (!pid_alive(pid)) return;

    log_event("killing", name, {{"pid", static_cast<double>(pid)}, {"signal", std::string("SIGTERM")}});
    kill(static_cast<pid_t>(pid), SIGTERM);

    // Wait up to 10s for graceful shutdown
    for (int i = 0; i < 20; i++) {
        if (!pid_alive(pid)) return;
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }

    // Force kill
    log_event("force_killing", name, {{"pid", static_cast<double>(pid)}, {"signal", std::string("SIGKILL")}});
    kill(static_cast<pid_t>(pid), SIGKILL);
}

static int start_process(const std::string& cmd, const std::string& log_path) {
    fs::create_directories(fs::path(log_path).parent_path());

    pid_t pid = fork();
    if (pid < 0) return 0;

    if (pid == 0) {
        // Child: detach, redirect output to log
        setsid();
        int fd = open(log_path.c_str(), O_WRONLY | O_CREAT | O_APPEND, 0666);
        if (fd >= 0) {
            dup2(fd, STDOUT_FILENO);
            dup2(fd, STDERR_FILENO);
            close(fd);
        }
        execl("/bin/bash", "bash", "-c", cmd.c_str(), nullptr);
        _exit(127);
    }

    return static_cast<int>(pid);
}

// ─── Process status check ───────────────────────────────

enum class ProcStatus { HEALTHY, RUNNING, UNHEALTHY, DEAD };

static const char* status_str(ProcStatus s) {
    switch (s) {
        case ProcStatus::HEALTHY:   return "healthy";
        case ProcStatus::RUNNING:   return "running";
        case ProcStatus::UNHEALTHY: return "unhealthy";
        case ProcStatus::DEAD:      return "dead";
    }
    return "unknown";
}

static ProcStatus check_process(zaya::JObject& entry) {
    int pid = 0;
    if (entry.count("pid") && entry["pid"].is_number())
        pid = entry["pid"].integer();

    // Try PID first, then pattern
    if (!pid_alive(pid)) {
        std::string pattern;
        if (entry.count("pattern") && entry["pattern"].is_string())
            pattern = entry["pattern"].str();
        else if (entry.count("cmd") && entry["cmd"].is_string())
            pattern = entry["cmd"].str().substr(0, entry["cmd"].str().find(' '));

        if (!pattern.empty())
            pid = find_pid_by_pattern(pattern);

        if (pid > 0)
            entry["pid"] = static_cast<double>(pid);
    }

    if (!pid_alive(pid))
        return ProcStatus::DEAD;

    // Health check
    if (entry.count("health") && entry["health"].is_string()) {
        return health_check(entry["health"].str()) ? ProcStatus::HEALTHY : ProcStatus::UNHEALTHY;
    }

    return ProcStatus::RUNNING;
}

// ─── Commands ───────────────────────────────────────────

static int cmd_register(int argc, char* argv[]) {
    if (argc < 3) {
        std::cerr << "Usage: register <name> --cmd '<cmd>' [options]" << std::endl;
        return 1;
    }

    std::string name = argv[2];
    std::string cmd, health_url, pattern, log_file;
    int max_restarts = DEFAULT_MAX_RESTARTS;
    int cooldown = DEFAULT_COOLDOWN;

    for (int i = 3; i < argc; i++) {
        std::string arg = argv[i];
        if (arg == "--cmd" && i + 1 < argc)          { cmd = argv[++i]; }
        else if (arg == "--health" && i + 1 < argc)   { health_url = argv[++i]; }
        else if (arg == "--pattern" && i + 1 < argc)   { pattern = argv[++i]; }
        else if (arg == "--max-restarts" && i + 1 < argc) { max_restarts = std::stoi(argv[++i]); }
        else if (arg == "--cooldown" && i + 1 < argc)  { cooldown = std::stoi(argv[++i]); }
        else if (arg == "--log-file" && i + 1 < argc)  { log_file = argv[++i]; }
    }

    if (cmd.empty()) {
        std::cerr << "Error: --cmd is required" << std::endl;
        return 1;
    }

    if (log_file.empty())
        log_file = std::string("/opt/zaya_os/hub/core/logs/") + name + ".log";

    // Find existing PID
    int pid = 0;
    if (!pattern.empty())
        pid = find_pid_by_pattern(pattern);
    else
        pid = find_pid_by_pattern(cmd.substr(0, cmd.find(' ')));

    using namespace zaya;
    JVal reg = load_registry();
    JObject entry;
    entry["name"]          = name;
    entry["cmd"]           = cmd;
    entry["log_file"]      = log_file;
    entry["max_restarts"]  = static_cast<double>(max_restarts);
    entry["cooldown"]      = static_cast<double>(cooldown);
    entry["pid"]           = static_cast<double>(pid);
    entry["restart_count"] = 0.0;
    entry["last_restart"]  = nullptr;
    entry["registered_at"] = now_iso();

    if (!health_url.empty()) entry["health"] = health_url;
    if (!pattern.empty())    entry["pattern"] = pattern;

    reg.obj()[name] = entry;
    save_registry(reg);

    log_event("registered", name, {{"cmd", cmd}});
    return 0;
}

static int cmd_unregister(const std::string& name) {
    using namespace zaya;
    JVal reg = load_registry();
    if (reg.obj().erase(name)) {
        save_registry(reg);
        log_event("unregistered", name);
    } else {
        std::cout << "Not found: " << name << std::endl;
    }
    return 0;
}

static int cmd_status() {
    using namespace zaya;
    JVal reg = load_registry();
    if (reg.obj().empty()) {
        std::cout << "No processes registered" << std::endl;
        return 0;
    }

    printf("%-15s %-8s %-12s %-10s %s\n", "NAME", "PID", "STATUS", "RESTARTS", "HEALTH");
    printf("%-15s %-8s %-12s %-10s %s\n", "---", "---", "---", "---", "---");

    for (auto& [name, val] : reg.obj()) {
        auto& entry = val.obj();
        ProcStatus status = check_process(entry);

        int pid = entry.count("pid") && entry["pid"].is_number() ? entry["pid"].integer() : 0;
        int restarts = entry.count("restart_count") && entry["restart_count"].is_number()
                     ? entry["restart_count"].integer() : 0;
        std::string health = entry.count("health") && entry["health"].is_string()
                           ? entry["health"].str() : "-";

        printf("%-15s %-8d %-12s %-10d %s\n",
            name.c_str(), pid, status_str(status), restarts, health.c_str());
    }

    // Save back (pid may have been updated by check_process)
    save_registry(reg);
    return 0;
}

static int cmd_run() {
    using namespace zaya;

    log_event("watchdog_started", "", {{"pid", static_cast<double>(getpid())}});
    std::cout << "[WATCHDOG] Started (PID " << getpid()
              << ") interval=" << CHECK_INTERVAL << "s" << std::endl;

    while (true) {
        JVal reg = load_registry();

        for (auto& [name, val] : reg.obj()) {
            if (!val.is_object()) continue;
            auto& entry = val.obj();

            ProcStatus status = check_process(entry);

            if (status == ProcStatus::HEALTHY || status == ProcStatus::RUNNING) {
                // Reset restart count on healthy
                if (status == ProcStatus::HEALTHY &&
                    entry.count("restart_count") && entry["restart_count"].is_number() &&
                    entry["restart_count"].integer() > 0) {
                    entry["restart_count"] = 0.0;
                    save_registry(reg);
                }
                continue;
            }

            // Dead or unhealthy — consider restart
            int max_r = entry.count("max_restarts") && entry["max_restarts"].is_number()
                      ? entry["max_restarts"].integer() : DEFAULT_MAX_RESTARTS;
            int count = entry.count("restart_count") && entry["restart_count"].is_number()
                      ? entry["restart_count"].integer() : 0;
            int cool  = entry.count("cooldown") && entry["cooldown"].is_number()
                      ? entry["cooldown"].integer() : DEFAULT_COOLDOWN;

            // Check restart limit
            if (count >= max_r) {
                if (count == max_r) {
                    log_event("restart_limit_reached", name, {{"restarts", static_cast<double>(count)}});
                    entry["restart_count"] = static_cast<double>(max_r + 1);
                    save_registry(reg);
                }
                continue;
            }

            // Check cooldown
            if (entry.count("last_restart") && entry["last_restart"].is_number()) {
                double elapsed = now_epoch() - entry["last_restart"].num();
                if (elapsed < cool) continue;
            }

            // Kill if unhealthy (hanging)
            if (status == ProcStatus::UNHEALTHY) {
                int pid = entry.count("pid") && entry["pid"].is_number() ? entry["pid"].integer() : 0;
                if (pid > 0) {
                    kill_process(pid, name);
                    std::this_thread::sleep_for(std::chrono::seconds(2));
                }
            }

            // Restart
            std::string cmd = entry.count("cmd") && entry["cmd"].is_string() ? entry["cmd"].str() : "";
            std::string lf  = entry.count("log_file") && entry["log_file"].is_string()
                            ? entry["log_file"].str()
                            : std::string("/opt/zaya_os/hub/core/logs/") + name + ".log";

            log_event("restarting", name, {{"status", std::string(status_str(status))},
                                           {"attempt", static_cast<double>(count + 1)}});

            int new_pid = start_process(cmd, lf);
            entry["pid"] = static_cast<double>(new_pid);
            entry["restart_count"] = static_cast<double>(count + 1);
            entry["last_restart"] = now_epoch();
            save_registry(reg);

            log_event("restarted", name, {{"pid", static_cast<double>(new_pid)}});

            // Wait for startup
            int wait = std::min(cool, 15);
            std::this_thread::sleep_for(std::chrono::seconds(wait));

            // Verify
            ProcStatus new_status = check_process(entry);
            save_registry(reg);

            if (new_status == ProcStatus::HEALTHY || new_status == ProcStatus::RUNNING)
                log_event("restart_success", name, {{"pid", static_cast<double>(new_pid)},
                                                    {"status", std::string(status_str(new_status))}});
            else
                log_event("restart_failed", name, {{"pid", static_cast<double>(new_pid)},
                                                   {"status", std::string(status_str(new_status))}});
        }

        std::this_thread::sleep_for(std::chrono::seconds(CHECK_INTERVAL));
    }

    return 0;
}

// ─── Main ───────────────────────────────────────────────

int main(int argc, char* argv[]) {
    if (argc < 2) {
        std::cout << "Zaya OS Kernel Watchdog v1 (C++)\n\n"
                  << "Commands:\n"
                  << "  register <name> --cmd '<cmd>' [--health <url>] [--pattern '<grep>']\n"
                  << "                  [--max-restarts N] [--cooldown N]\n"
                  << "  unregister <name>\n"
                  << "  status\n"
                  << "  run             — start watchdog daemon\n";
        return 0;
    }

    std::string cmd = argv[1];

    if (cmd == "register")   return cmd_register(argc, argv);
    if (cmd == "status")     return cmd_status();
    if (cmd == "run")        return cmd_run();

    if (cmd == "unregister" && argc >= 3)
        return cmd_unregister(argv[2]);

    std::cerr << "Unknown command: " << cmd << std::endl;
    return 1;
}
