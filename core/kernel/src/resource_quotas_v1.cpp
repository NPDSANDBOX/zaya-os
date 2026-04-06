// Zaya OS Kernel — Resource Quotas v1
// Per-agent resource limits for CPU, RAM, and VRAM.
// Prevents any single process from monopolizing system resources.
//
// Usage:
//   resource_quotas_v1 set <name> --vram <MB> --ram <MB> --cpu <percent>
//                      [--pattern '<grep>'] [--action warn|throttle|kill]
//   resource_quotas_v1 remove <name>
//   resource_quotas_v1 check <name> [--pid <PID>]
//   resource_quotas_v1 status
//   resource_quotas_v1 summary
//   resource_quotas_v1 enforce
//
// Quotas:  /opt/zaya_os/hub/core/state/resource_quotas.json
// Logs:    /opt/zaya_os/hub/core/logs/quota_enforcer.jsonl

#include "zaya/kjson.hpp"
#include <iostream>
#include <filesystem>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <array>
#include <sstream>
#include <fstream>
#include <thread>

// POSIX
#include <signal.h>
#include <unistd.h>

namespace fs = std::filesystem;

static const char* QUOTA_FILE = "/opt/zaya_os/hub/core/state/resource_quotas.json";
static const char* LOG_FILE   = "/opt/zaya_os/hub/core/logs/quota_enforcer.jsonl";

// ─── Utilities ──────────────────────────────────────────

static std::string now_iso() {
    auto tp = std::chrono::system_clock::now();
    auto tt = std::chrono::system_clock::to_time_t(tp);
    char buf[64];
    std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", std::gmtime(&tt));
    return buf;
}

static void log_event(const std::string& event, const std::string& agent = "",
                      const zaya::JObject& extra = {}) {
    using namespace zaya;
    JObject entry;
    entry["ts"] = now_iso();
    entry["event"] = event;
    if (!agent.empty()) entry["agent"] = agent;
    for (const auto& [k, v] : extra) entry[k] = v;

    fs::create_directories(fs::path(LOG_FILE).parent_path());
    std::ofstream f(LOG_FILE, std::ios::app);
    f << json_dump(entry) << "\n";
    std::cout << json_dump(entry) << std::endl;
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

static zaya::JVal load_quotas() {
    using namespace zaya;
    if (!fs::exists(QUOTA_FILE)) return JObject{};
    JVal v = json_load_file(QUOTA_FILE);
    return v.is_object() ? v : JVal(JObject{});
}

static void save_quotas(const zaya::JVal& q) {
    fs::create_directories(fs::path(QUOTA_FILE).parent_path());
    zaya::json_save_file(QUOTA_FILE, q);
}

// ─── Resource queries ───────────────────────────────────

static int get_process_vram(int pid) {
    std::string out = exec_cmd(
        "nvidia-smi --query-compute-apps=pid,used_memory "
        "--format=csv,noheader,nounits 2>/dev/null");
    std::istringstream ss(out);
    std::string line;
    while (std::getline(ss, line)) {
        auto comma = line.find(',');
        if (comma == std::string::npos) continue;
        int p = std::stoi(line.substr(0, comma));
        if (p == pid)
            return std::stoi(line.substr(comma + 1));
    }
    return 0;
}

static int get_process_ram(int pid) {
    // Read VmRSS from /proc/[pid]/status
    std::string path = "/proc/" + std::to_string(pid) + "/status";
    std::ifstream f(path);
    if (!f) return 0;
    std::string line;
    while (std::getline(f, line)) {
        if (line.substr(0, 6) == "VmRSS:") {
            std::istringstream ss(line.substr(6));
            int kb;
            ss >> kb;
            return kb / 1024; // MB
        }
    }
    return 0;
}

static double get_process_cpu(int pid) {
    // Read /proc/[pid]/stat twice with 1s interval
    auto read_stat = [](int p) -> std::pair<long, long> {
        std::string path = "/proc/" + std::to_string(p) + "/stat";
        std::ifstream f(path);
        if (!f) return {0, 0};
        std::string content;
        std::getline(f, content);

        // Skip past comm field (may contain spaces in parens)
        auto close_paren = content.rfind(')');
        if (close_paren == std::string::npos) return {0, 0};
        std::istringstream ss(content.substr(close_paren + 2));

        std::string tok;
        // Fields after comm: state(1) ppid(2) pgrp(3) session(4) tty(5) tpgid(6)
        // flags(7) minflt(8) cminflt(9) majflt(10) cmajflt(11) utime(12) stime(13)
        for (int i = 0; i < 11; i++) ss >> tok;
        long utime, stime;
        ss >> utime >> stime;

        // System uptime in jiffies
        std::ifstream sf("/proc/stat");
        std::string cpu_line;
        std::getline(sf, cpu_line);
        std::istringstream css(cpu_line.substr(4));
        long total = 0;
        long v;
        while (css >> v) total += v;

        return {utime + stime, total};
    };

    auto [proc1, sys1] = read_stat(pid);
    std::this_thread::sleep_for(std::chrono::seconds(1));
    auto [proc2, sys2] = read_stat(pid);

    long dp = proc2 - proc1;
    long ds = sys2 - sys1;
    if (ds <= 0) return 0.0;

    int ncpu = sysconf(_SC_NPROCESSORS_ONLN);
    return (static_cast<double>(dp) / ds) * 100.0 * ncpu;
}

static int find_pid(const std::string& pattern) {
    std::string out = exec_cmd("pgrep -f '" + pattern + "' 2>/dev/null");
    int my_pid = getpid();
    std::istringstream ss(out);
    std::string line;
    while (std::getline(ss, line)) {
        if (line.empty()) continue;
        int pid = std::stoi(line);
        if (pid != my_pid) return pid;
    }
    return 0;
}

static int get_system_vram() {
    std::string out = exec_cmd(
        "nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null");
    if (out.empty()) return 0;
    return std::stoi(out);
}

static int get_system_ram() {
    std::ifstream f("/proc/meminfo");
    std::string line;
    while (std::getline(f, line)) {
        if (line.substr(0, 9) == "MemTotal:") {
            std::istringstream ss(line.substr(9));
            int kb; ss >> kb;
            return kb / 1024;
        }
    }
    return 0;
}

static int get_free_vram() {
    std::string out = exec_cmd(
        "nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null");
    if (out.empty()) return 0;
    return std::stoi(out);
}

static int get_free_ram() {
    std::ifstream f("/proc/meminfo");
    std::string line;
    while (std::getline(f, line)) {
        if (line.substr(0, 13) == "MemAvailable:") {
            std::istringstream ss(line.substr(13));
            int kb; ss >> kb;
            return kb / 1024;
        }
    }
    return 0;
}

// ─── Check logic ────────────────────────────────────────

struct CheckResult {
    std::string name;
    std::string status;    // "ok", "violation", "no_quota", "not_running"
    std::string action;
    int pid = 0;
    int vram_mb = 0, vram_limit = 0;
    int ram_mb = 0, ram_limit = 0;
    double cpu_pct = 0, cpu_limit = 0;
    std::vector<std::string> violations;
};

static CheckResult check_agent(const std::string& name, zaya::JObject& quota, int forced_pid = 0) {
    CheckResult r;
    r.name = name;
    r.action = quota.count("action") && quota["action"].is_string() ? quota["action"].str() : "warn";

    int pid = forced_pid;
    if (pid <= 0 && quota.count("pattern") && quota["pattern"].is_string())
        pid = find_pid(quota["pattern"].str());
    if (pid <= 0) {
        r.status = "not_running";
        return r;
    }
    r.pid = pid;

    // VRAM
    if (quota.count("vram_mb") && quota["vram_mb"].is_number()) {
        r.vram_limit = quota["vram_mb"].integer();
        r.vram_mb = get_process_vram(pid);
        if (r.vram_mb > r.vram_limit)
            r.violations.push_back("VRAM " + std::to_string(r.vram_mb) + "MB > " +
                                   std::to_string(r.vram_limit) + "MB limit");
    }

    // RAM
    if (quota.count("ram_mb") && quota["ram_mb"].is_number()) {
        r.ram_limit = quota["ram_mb"].integer();
        r.ram_mb = get_process_ram(pid);
        if (r.ram_mb > r.ram_limit)
            r.violations.push_back("RAM " + std::to_string(r.ram_mb) + "MB > " +
                                   std::to_string(r.ram_limit) + "MB limit");
    }

    // CPU
    if (quota.count("cpu_percent") && quota["cpu_percent"].is_number()) {
        r.cpu_limit = quota["cpu_percent"].num();
        r.cpu_pct = get_process_cpu(pid);
        if (r.cpu_pct > r.cpu_limit) {
            char buf[64];
            snprintf(buf, sizeof(buf), "CPU %.1f%% > %.0f%% limit", r.cpu_pct, r.cpu_limit);
            r.violations.push_back(buf);
        }
    }

    r.status = r.violations.empty() ? "ok" : "violation";
    return r;
}

// ─── Commands ───────────────────────────────────────────

static int cmd_set(int argc, char* argv[]) {
    if (argc < 3) {
        std::cerr << "Usage: set <name> --vram <MB> --ram <MB> --cpu <%> [--pattern '<grep>'] [--action warn|throttle|kill]" << std::endl;
        return 1;
    }

    std::string name = argv[2];
    using namespace zaya;
    JObject entry;
    entry["name"] = name;
    entry["set_at"] = now_iso();

    for (int i = 3; i < argc; i++) {
        std::string arg = argv[i];
        if (arg == "--vram" && i + 1 < argc)    { entry["vram_mb"] = static_cast<double>(std::stoi(argv[++i])); }
        else if (arg == "--ram" && i + 1 < argc) { entry["ram_mb"] = static_cast<double>(std::stoi(argv[++i])); }
        else if (arg == "--cpu" && i + 1 < argc) { entry["cpu_percent"] = std::stod(argv[++i]); }
        else if (arg == "--pattern" && i + 1 < argc) { entry["pattern"] = std::string(argv[++i]); }
        else if (arg == "--action" && i + 1 < argc)  { entry["action"] = std::string(argv[++i]); }
    }

    JVal quotas = load_quotas();
    quotas.obj()[name] = entry;
    save_quotas(quotas);

    JObject extra;
    if (entry.count("vram_mb"))     extra["vram_mb"] = entry["vram_mb"];
    if (entry.count("ram_mb"))      extra["ram_mb"] = entry["ram_mb"];
    if (entry.count("cpu_percent")) extra["cpu_percent"] = entry["cpu_percent"];
    if (entry.count("action"))      extra["action"] = entry["action"];
    log_event("quota_set", name, extra);
    return 0;
}

static int cmd_remove(const std::string& name) {
    using namespace zaya;
    JVal quotas = load_quotas();
    if (quotas.obj().erase(name)) {
        save_quotas(quotas);
        log_event("quota_removed", name);
    } else {
        std::cout << "Not found: " << name << std::endl;
    }
    return 0;
}

static int cmd_check(int argc, char* argv[]) {
    if (argc < 3) { std::cerr << "Usage: check <name> [--pid N]" << std::endl; return 1; }

    std::string name = argv[2];
    int pid = 0;
    for (int i = 3; i < argc; i++)
        if (std::string(argv[i]) == "--pid" && i + 1 < argc) pid = std::stoi(argv[++i]);

    using namespace zaya;
    JVal quotas = load_quotas();
    if (!quotas.has(name)) {
        std::cout << json_dump(JObject{{"name", name}, {"status", std::string("no_quota")}}, 2) << std::endl;
        return 0;
    }

    auto result = check_agent(name, quotas.obj()[name].obj(), pid);

    JObject out;
    out["name"] = result.name;
    out["status"] = result.status;
    out["pid"] = static_cast<double>(result.pid);
    if (result.vram_limit > 0) {
        out["vram_mb"] = static_cast<double>(result.vram_mb);
        out["vram_limit"] = static_cast<double>(result.vram_limit);
    }
    if (result.ram_limit > 0) {
        out["ram_mb"] = static_cast<double>(result.ram_mb);
        out["ram_limit"] = static_cast<double>(result.ram_limit);
    }
    if (result.cpu_limit > 0) {
        out["cpu_percent"] = result.cpu_pct;
        out["cpu_limit"] = result.cpu_limit;
    }
    if (!result.violations.empty()) {
        JArray viols;
        for (const auto& v : result.violations) viols.push_back(v);
        out["violations"] = viols;
    }
    std::cout << json_dump(out, 2) << std::endl;
    return 0;
}

static int cmd_status() {
    using namespace zaya;
    JVal quotas = load_quotas();
    if (quotas.obj().empty()) {
        std::cout << "No quotas defined" << std::endl;
        return 0;
    }

    printf("%-12s %-8s %-18s %-18s %-15s %s\n", "AGENT", "PID", "VRAM", "RAM", "CPU", "STATUS");
    printf("%-12s %-8s %-18s %-18s %-15s %s\n", "---", "---", "---", "---", "---", "---");

    for (auto& [name, val] : quotas.obj()) {
        if (!val.is_object()) continue;
        auto result = check_agent(name, val.obj());

        char vram[32] = "-", ram[32] = "-", cpu[32] = "-";
        if (result.vram_limit > 0)
            snprintf(vram, sizeof(vram), "%d/%dMB", result.vram_mb, result.vram_limit);
        if (result.ram_limit > 0)
            snprintf(ram, sizeof(ram), "%d/%dMB", result.ram_mb, result.ram_limit);
        if (result.cpu_limit > 0)
            snprintf(cpu, sizeof(cpu), "%.1f/%.0f%%", result.cpu_pct, result.cpu_limit);

        const char* status = result.status == "violation" ? "VIOLATION" :
                             result.status == "ok" ? "OK" :
                             result.status == "not_running" ? "NOT_RUNNING" : "UNKNOWN";

        printf("%-12s %-8d %-18s %-18s %-15s %s\n",
            name.c_str(), result.pid, vram, ram, cpu, status);
    }
    return 0;
}

static int cmd_summary() {
    using namespace zaya;
    JVal quotas = load_quotas();

    int sys_vram = get_system_vram();
    int sys_ram = get_system_ram();
    int ncpu = sysconf(_SC_NPROCESSORS_ONLN);

    int alloc_vram = 0, alloc_ram = 0;
    for (const auto& [_, v] : quotas.obj()) {
        if (!v.is_object()) continue;
        if (v.has("vram_mb") && v["vram_mb"].is_number()) alloc_vram += v["vram_mb"].integer();
        if (v.has("ram_mb") && v["ram_mb"].is_number())   alloc_ram += v["ram_mb"].integer();
    }

    JObject out;
    out["system"] = JObject{
        {"vram_total_mb", static_cast<double>(sys_vram)},
        {"ram_total_mb", static_cast<double>(sys_ram)},
        {"cpu_cores", static_cast<double>(ncpu)},
        {"vram_free_mb", static_cast<double>(get_free_vram())},
        {"ram_free_mb", static_cast<double>(get_free_ram())}
    };
    out["allocated"] = JObject{
        {"vram_mb", static_cast<double>(alloc_vram)},
        {"ram_mb", static_cast<double>(alloc_ram)},
        {"agents", static_cast<double>(quotas.obj().size())}
    };
    out["headroom"] = JObject{
        {"vram_mb", static_cast<double>(sys_vram - alloc_vram)},
        {"ram_mb", static_cast<double>(sys_ram - alloc_ram)}
    };

    std::cout << json_dump(out, 2) << std::endl;
    return 0;
}

static int cmd_enforce() {
    using namespace zaya;
    JVal quotas = load_quotas();
    bool any = false;

    for (auto& [name, val] : quotas.obj()) {
        if (!val.is_object()) continue;
        auto result = check_agent(name, val.obj());
        if (result.status != "violation") continue;
        any = true;

        JArray viols;
        for (const auto& v : result.violations) viols.push_back(v);
        log_event("quota_violation", name, {{"violations", viols}, {"action", result.action}});

        if (result.action == "throttle" && result.pid > 0) {
            kill(static_cast<pid_t>(result.pid), SIGSTOP);
            log_event("throttled", name, {{"pid", static_cast<double>(result.pid)}});
            std::this_thread::sleep_for(std::chrono::seconds(5));
            kill(static_cast<pid_t>(result.pid), SIGCONT);
            log_event("resumed", name, {{"pid", static_cast<double>(result.pid)}});
        } else if (result.action == "kill" && result.pid > 0) {
            kill(static_cast<pid_t>(result.pid), SIGTERM);
            log_event("killed", name, {{"pid", static_cast<double>(result.pid)}});
        }
    }

    if (!any) std::cout << "All agents within quota" << std::endl;
    return 0;
}

// ─── Main ───────────────────────────────────────────────

int main(int argc, char* argv[]) {
    if (argc < 2) {
        std::cout << "Zaya OS Resource Quotas v1 (C++)\n\n"
                  << "Commands:\n"
                  << "  set <name> --vram <MB> --ram <MB> --cpu <%> [--pattern '<grep>'] [--action warn|throttle|kill]\n"
                  << "  remove <name>\n"
                  << "  check <name> [--pid <PID>]\n"
                  << "  status\n"
                  << "  summary\n"
                  << "  enforce\n";
        return 0;
    }

    std::string cmd = argv[1];

    if (cmd == "set")     return cmd_set(argc, argv);
    if (cmd == "status")  return cmd_status();
    if (cmd == "summary") return cmd_summary();
    if (cmd == "enforce") return cmd_enforce();
    if (cmd == "check")   return cmd_check(argc, argv);

    if (cmd == "remove" && argc >= 3) return cmd_remove(argv[2]);

    std::cerr << "Unknown command: " << cmd << std::endl;
    return 1;
}
