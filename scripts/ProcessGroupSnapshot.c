/* Read-only process-group witness for an unreaped child owned by the caller.
 * No signals, waits, privilege changes, files or subprocesses. Build with the
 * Apple SDK so no Darwin structure layout is duplicated in Python.
 */
#define _DARWIN_C_SOURCE 1
#include <errno.h>
#include <limits.h>
#include <libproc.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/proc.h>
#include <sys/proc_info.h>
#include <sys/sysctl.h>

#define MAX_MEMBERS 4096
#define MAX_SYSCTL_BYTES (4 * 1024 * 1024)

struct member { int pid, pgid, status; };
struct snapshot { size_t count; struct member members[MAX_MEMBERS]; };

static int member_order(const void *a, const void *b) {
    const struct member *left = a, *right = b;
    return (left->pid > right->pid) - (left->pid < right->pid);
}

static bool validate(struct snapshot *value, int group) {
    if (!value->count || value->count > MAX_MEMBERS) return false;
    qsort(value->members, value->count, sizeof(value->members[0]), member_order);
    bool leader = false;
    for (size_t index = 0; index < value->count; index++) {
        const struct member *item = &value->members[index];
        if (item->pid <= 0 || item->pgid != group || item->status < SIDL || item->status > SZOMB
                || (index && value->members[index - 1].pid == item->pid)) return false;
        leader |= item->pid == group;
    }
    return leader;
}

static bool library_snapshot(int group, struct snapshot *value) {
    /* One extra slot distinguishes an exact supported count from truncation.
       The NULL-buffer estimate is system-wide and is not a group count. */
    int pids[MAX_MEMBERS + 1];
    int bytes = proc_listpids(PROC_PGRP_ONLY, (uint32_t)group, pids, (int)sizeof(pids));
    if (bytes <= 0 || bytes >= (int)sizeof(pids) || bytes % (int)sizeof(int)) return false;
    value->count = (size_t)bytes / sizeof(int);
    for (size_t index = 0; index < value->count; index++) {
        struct proc_bsdinfo info;
        memset(&info, 0, sizeof(info));
        /* XNU's public TBSDINFO implementation includes zombies for arg=1;
           arg=0 returns ESRCH for them. Both real supported SDKs were probed. */
        int received = proc_pidinfo(pids[index], PROC_PIDTBSDINFO, 1, &info, (int)sizeof(info));
        if (pids[index] <= 0 || received != (int)sizeof(info)
                || info.pbi_pid != (uint32_t)pids[index] || info.pbi_pgid != (uint32_t)group
                || info.pbi_status > INT_MAX) return false;
        value->members[index] = (struct member){pids[index], (int)info.pbi_pgid, (int)info.pbi_status};
    }
    return validate(value, group);
}

static bool sysctl_snapshot(int group, struct snapshot *value) {
    int query[] = {CTL_KERN, KERN_PROC, KERN_PROC_PGRP, group};
    size_t estimate = 0;
    if (sysctl(query, 4, NULL, &estimate, NULL, 0) || estimate > MAX_SYSCTL_BYTES) return false;
    size_t capacity = estimate + 16 * sizeof(struct kinfo_proc);
    if (capacity < estimate || capacity > MAX_SYSCTL_BYTES) return false;
    struct kinfo_proc *items = calloc(1, capacity);
    if (!items) return false;
    size_t bytes = capacity;
    bool valid = sysctl(query, 4, items, &bytes, NULL, 0) == 0 && bytes > 0
        && bytes < capacity && bytes % sizeof(*items) == 0 && bytes / sizeof(*items) <= MAX_MEMBERS;
    if (valid) {
        value->count = bytes / sizeof(*items);
        for (size_t index = 0; index < value->count; index++) {
            value->members[index] = (struct member){items[index].kp_proc.p_pid,
                items[index].kp_eproc.e_pgid, items[index].kp_proc.p_stat};
        }
        valid = validate(value, group);
    }
    free(items);
    return valid;
}

static bool equal(const struct snapshot *a, const struct snapshot *b) {
    if (a->count != b->count) return false;
    for (size_t index = 0; index < a->count; index++) {
        if (a->members[index].pid != b->members[index].pid
                || a->members[index].pgid != b->members[index].pgid
                || a->members[index].status != b->members[index].status) return false;
    }
    return true;
}

int main(int argc, char **argv) {
    if (argc != 2 || !argv[1][0]) return 2;
    for (const char *cursor = argv[1]; *cursor; cursor++) if (*cursor < '0' || *cursor > '9') return 2;
    errno = 0; char *end = NULL; long number = strtol(argv[1], &end, 10);
    if (errno || !end || *end || number <= 0 || number > INT_MAX) return 2;
    int group = (int)number;
    struct snapshot *snapshots = calloc(4, sizeof(struct snapshot));
    if (!snapshots) return 2;
    bool complete = library_snapshot(group, &snapshots[0]) && sysctl_snapshot(group, &snapshots[1])
        && library_snapshot(group, &snapshots[2]) && sysctl_snapshot(group, &snapshots[3]);
    bool stable = complete && equal(&snapshots[0], &snapshots[1])
        && equal(&snapshots[0], &snapshots[2]) && equal(&snapshots[0], &snapshots[3]);
    if (!stable) {
        free(snapshots);
        fputs("A complete stable process-group snapshot is unavailable.\n", stderr);
        return 2;
    }
    bool zombies = true;
    for (size_t index = 0; index < snapshots[0].count; index++) zombies &= snapshots[0].members[index].status == SZOMB;
    printf("{\"schemaVersion\":1,\"pgid\":%d,\"zombieState\":%d,\"libprocComplete\":true,"
           "\"sysctlComplete\":true,\"stable\":true,\"leaderPresent\":true,\"allZombies\":%s,\"members\":[",
           group, SZOMB, zombies ? "true" : "false");
    for (size_t index = 0; index < snapshots[0].count; index++) {
        const struct member *item = &snapshots[0].members[index];
        if (index) putchar(',');
        printf("{\"pid\":%d,\"pgid\":%d,\"status\":%d}", item->pid, item->pgid, item->status);
    }
    puts("]}");
    free(snapshots);
    return ferror(stdout) ? 2 : 0;
}
