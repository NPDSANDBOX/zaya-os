#!/usr/bin/env bash
set -euo pipefail

SRC="/opt/zaya_os/core/kernel/src"
INC="/opt/zaya_os/core/kernel/include"
BIN="/opt/zaya_os/core/kernel/bin"

mkdir -p "$BIN"

echo "[KERNEL] Building Zaya OS Kernel Modules..."

g++ -std=c++20 -O2 "$SRC/gpu_scheduler_v4_priority.cpp" -I"$INC" -o "$BIN/gpu_scheduler_v4_priority"
echo "  ✓ gpu_scheduler_v4_priority"

g++ -std=c++20 -O2 "$SRC/checkpoint_manager_v1.cpp" -I"$INC" -o "$BIN/checkpoint_manager_v1"
echo "  ✓ checkpoint_manager_v1"

g++ -std=c++20 -O2 "$SRC/shared_memory_bus_v1.cpp" -I"$INC" -lrt -o "$BIN/shared_memory_bus_v1"
echo "  ✓ shared_memory_bus_v1"

g++ -std=c++20 -O2 "$SRC/kernel_watchdog_v1.cpp" -I"$INC" -pthread -o "$BIN/kernel_watchdog_v1"
echo "  ✓ kernel_watchdog_v1"

g++ -std=c++20 -O2 "$SRC/resource_quotas_v1.cpp" -I"$INC" -pthread -o "$BIN/resource_quotas_v1"
echo "  ✓ resource_quotas_v1"

echo "[KERNEL] All 5 modules built successfully."
