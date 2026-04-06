// Zaya OS Kernel — Shared Memory Bus v1
// Inter-agent communication via POSIX shared memory.
// Zero external dependencies — uses shm_open/mmap from POSIX.
//
// Usage:
//   shared_memory_bus_v1 publish <channel> <json>   — write to channel
//   shared_memory_bus_v1 read <channel>             — read from channel
//   shared_memory_bus_v1 list                       — list active channels
//   shared_memory_bus_v1 clear <channel>            — zero out channel
//   shared_memory_bus_v1 destroy <channel>          — free shared memory
//   shared_memory_bus_v1 bench                      — benchmark vs JSON file
//
// Each channel: 64KB POSIX shared memory segment.
// Format: [4 bytes length][JSON payload]
// Persists until reboot or explicit destroy.

#include "zaya/kjson.hpp"
#include <iostream>
#include <cstring>
#include <chrono>
#include <filesystem>

// POSIX shared memory
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <dirent.h>

static constexpr size_t CHANNEL_SIZE = 65536; // 64KB
static constexpr const char* PREFIX = "zaya_";

static std::string shm_name(const std::string& channel) {
    return std::string("/") + PREFIX + channel;
}

// ─── Core operations ────────────────────────────────────

static bool shm_publish(const std::string& channel, const std::string& payload) {
    if (payload.size() + 4 >= CHANNEL_SIZE) {
        std::cerr << "Payload too large: " << payload.size() << " bytes" << std::endl;
        return false;
    }

    std::string name = shm_name(channel);

    int fd = shm_open(name.c_str(), O_CREAT | O_RDWR, 0666);
    if (fd < 0) {
        perror("shm_open");
        return false;
    }

    ftruncate(fd, CHANNEL_SIZE);

    void* ptr = mmap(nullptr, CHANNEL_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);

    if (ptr == MAP_FAILED) {
        perror("mmap");
        return false;
    }

    auto* buf = static_cast<char*>(ptr);

    // Write length (4 bytes little-endian) + payload
    uint32_t len = static_cast<uint32_t>(payload.size());
    std::memcpy(buf, &len, 4);
    std::memcpy(buf + 4, payload.data(), len);

    munmap(ptr, CHANNEL_SIZE);
    return true;
}

static std::string shm_read(const std::string& channel) {
    std::string name = shm_name(channel);

    int fd = shm_open(name.c_str(), O_RDONLY, 0);
    if (fd < 0) return "";

    void* ptr = mmap(nullptr, CHANNEL_SIZE, PROT_READ, MAP_SHARED, fd, 0);
    close(fd);

    if (ptr == MAP_FAILED) return "";

    auto* buf = static_cast<const char*>(ptr);

    uint32_t len = 0;
    std::memcpy(&len, buf, 4);

    std::string result;
    if (len > 0 && len < CHANNEL_SIZE - 4) {
        result.assign(buf + 4, len);
    }

    munmap(const_cast<void*>(ptr), CHANNEL_SIZE);
    return result;
}

static void shm_clear(const std::string& channel) {
    std::string name = shm_name(channel);

    int fd = shm_open(name.c_str(), O_RDWR, 0);
    if (fd < 0) return;

    void* ptr = mmap(nullptr, CHANNEL_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);

    if (ptr == MAP_FAILED) return;

    // Zero the length header
    uint32_t zero = 0;
    std::memcpy(ptr, &zero, 4);

    munmap(ptr, CHANNEL_SIZE);
}

static void shm_destroy(const std::string& channel) {
    std::string name = shm_name(channel);
    shm_unlink(name.c_str());
}

static std::vector<std::string> shm_list() {
    std::vector<std::string> channels;
    size_t prefix_len = std::strlen(PREFIX);

    DIR* dir = opendir("/dev/shm");
    if (!dir) return channels;

    struct dirent* entry;
    while ((entry = readdir(dir)) != nullptr) {
        std::string name = entry->d_name;
        if (name.substr(0, prefix_len) == PREFIX) {
            channels.push_back(name.substr(prefix_len));
        }
    }
    closedir(dir);

    std::sort(channels.begin(), channels.end());
    return channels;
}

// ─── Commands ───────────────────────────────────────────

static int cmd_publish(const std::string& channel, const std::string& json_data) {
    using namespace zaya;

    // Wrap in envelope with timestamp and pid
    auto tp = std::chrono::system_clock::now();
    double ts = std::chrono::duration<double>(tp.time_since_epoch()).count();

    JObject envelope;
    envelope["ts"]   = ts;
    envelope["pid"]  = static_cast<double>(getpid());
    envelope["data"] = json_parse(json_data);

    std::string payload = json_dump(envelope);

    if (shm_publish(channel, payload)) {
        std::cout << "Published to " << channel << std::endl;
        return 0;
    }
    return 1;
}

static int cmd_read(const std::string& channel) {
    using namespace zaya;

    std::string raw = shm_read(channel);
    if (raw.empty()) {
        std::cout << "(empty)" << std::endl;
        return 0;
    }

    JVal envelope = json_parse(raw);
    if (envelope.is_object() && envelope.has("data")) {
        std::cout << json_dump(envelope["data"], 2) << std::endl;
    } else {
        std::cout << raw << std::endl;
    }
    return 0;
}

static int cmd_list() {
    auto channels = shm_list();
    if (channels.empty()) {
        std::cout << "No active channels" << std::endl;
        return 0;
    }

    using namespace zaya;
    for (const auto& ch : channels) {
        std::string raw = shm_read(ch);
        if (!raw.empty()) {
            JVal env = json_parse(raw);
            if (env.is_object()) {
                int pid = env.has("pid") && env["pid"].is_number() ? env["pid"].integer() : 0;
                long long ts = env.has("ts") && env["ts"].is_number() ? static_cast<long long>(env["ts"].num()) : 0;
                std::cout << "  " << ch << ": pid=" << pid
                          << " ts=" << ts << std::endl;
                continue;
            }
        }
        std::cout << "  " << ch << ": (empty)" << std::endl;
    }
    return 0;
}

static int cmd_bench() {
    using namespace zaya;
    namespace chrono = std::chrono;

    constexpr int ROUNDS = 10000;
    const std::string channel = "_bench_cpp";
    const std::string json_file = "/opt/zaya_os/hub/data/contracts/_bench_cpp.json";

    JObject test_data;
    test_data["gpu_locked"] = true;
    test_data["owner"]      = std::string("flux1");
    test_data["vram_free"]  = 4096.0;
    test_data["pid"]        = 12345.0;

    JObject envelope;
    envelope["ts"]   = 0.0;
    envelope["pid"]  = 0.0;
    envelope["data"] = test_data;

    std::string payload = json_dump(envelope);

    // ── Benchmark: Shared Memory ──
    auto t0 = chrono::high_resolution_clock::now();
    for (int i = 0; i < ROUNDS; i++) {
        shm_publish(channel, payload);
        shm_read(channel);
    }
    auto t1 = chrono::high_resolution_clock::now();
    double shm_secs = chrono::duration<double>(t1 - t0).count();
    shm_destroy(channel);

    // ── Benchmark: JSON File (with fsync) ──
    std::string file_content = json_dump(test_data, 2);
    t0 = chrono::high_resolution_clock::now();
    for (int i = 0; i < ROUNDS; i++) {
        // Write
        int fd = open(json_file.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0666);
        if (fd >= 0) {
            write(fd, file_content.data(), file_content.size());
            fsync(fd);
            close(fd);
        }
        // Read
        std::ifstream f(json_file);
        std::stringstream ss;
        ss << f.rdbuf();
        json_parse(ss.str());
    }
    t1 = chrono::high_resolution_clock::now();
    double json_secs = chrono::duration<double>(t1 - t0).count();
    std::filesystem::remove(json_file);

    std::cout << "Rounds: " << ROUNDS << std::endl;
    std::cout << "Shared Memory: " << shm_secs << "s ("
              << static_cast<int>(ROUNDS / shm_secs) << " ops/s)" << std::endl;
    std::cout << "JSON+fsync:    " << json_secs << "s ("
              << static_cast<int>(ROUNDS / json_secs) << " ops/s)" << std::endl;
    std::cout << "Speedup:       " << (json_secs / shm_secs) << "x faster" << std::endl;

    return 0;
}

// ─── Main ───────────────────────────────────────────────

int main(int argc, char* argv[]) {
    if (argc < 2) {
        std::cout << "Zaya OS Shared Memory Bus v1 (C++)\n\n"
                  << "Commands:\n"
                  << "  publish <channel> <json>  — write to channel\n"
                  << "  read <channel>            — read from channel\n"
                  << "  list                      — list active channels\n"
                  << "  clear <channel>           — clear channel\n"
                  << "  destroy <channel>         — destroy channel\n"
                  << "  bench                     — benchmark vs JSON file\n";
        return 0;
    }

    std::string cmd = argv[1];

    if (cmd == "list")
        return cmd_list();

    if (cmd == "bench")
        return cmd_bench();

    if (argc < 3) {
        std::cerr << "Missing channel name" << std::endl;
        return 1;
    }

    std::string channel = argv[2];

    if (cmd == "publish" && argc >= 4)
        return cmd_publish(channel, argv[3]);

    if (cmd == "read")
        return cmd_read(channel);

    if (cmd == "clear") {
        shm_clear(channel);
        std::cout << "Cleared " << channel << std::endl;
        return 0;
    }

    if (cmd == "destroy") {
        shm_destroy(channel);
        std::cout << "Destroyed " << channel << std::endl;
        return 0;
    }

    std::cerr << "Unknown command: " << cmd << std::endl;
    return 1;
}
