/* Synthetic macOS process-group evidence; never an application approval.
 * Build against the selected Apple SDK: no handwritten struct layout.
 * Public declarations: libproc.h, sys/proc_info.h, sys/sysctl.h, sys/proc.h.
 * Apple XNU proc_info.c permits zombie lookup for TBSDINFO when arg != 0;
 * both arg=0 and arg=1 are recorded, never inferred to be equivalent.
 */
#define _DARWIN_C_SOURCE 1
#include <errno.h>
#include <fcntl.h>
#include <libproc.h>
#include <poll.h>
#include <signal.h>
#include <spawn.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/event.h>
#include <sys/proc.h>
#include <sys/proc_info.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t interrupted = 0;
static void interrupt_handler(int value) { interrupted = value; }
static double monotonic(void) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now)) _exit(91);
    return (double)now.tv_sec + (double)now.tv_nsec / 1000000000.0;
}
static const char *boolean(bool value) { return value ? "true" : "false"; }
static int integer_order(const void *a, const void *b) {
    int left = *(const int *)a, right = *(const int *)b;
    return (left > right) - (left < right);
}

static void library_snapshot(pid_t group) {
    int pids[16384], second[16384];
    errno = 0;
    int estimate = proc_listpids(PROC_PGRP_ONLY, (uint32_t)group, NULL, 0);
    int estimate_error = errno;
    errno = 0;
    int bytes = proc_listpids(PROC_PGRP_ONLY, (uint32_t)group, pids, (int)sizeof(pids));
    int list_error = errno;
    bool complete = estimate > 0 && estimate < (int)sizeof(pids) && bytes > 0
        && bytes < (int)sizeof(pids) && bytes % (int)sizeof(int) == 0;
    int count = complete ? bytes / (int)sizeof(int) : 0;
    bool leader = false, zombies = complete;
    printf("\"libproc\":{\"estimatedBytes\":%d,\"estimateErrno\":%d,\"bytes\":%d,\"listErrno\":%d,\"members\":[",
           estimate, estimate_error, bytes, list_error);
    for (int index = 0; index < count; index++) {
        if (index) putchar(',');
        struct proc_bsdinfo zero, one;
        memset(&zero, 0, sizeof(zero)); memset(&one, 0, sizeof(one));
        errno = 0;
        int zero_bytes = proc_pidinfo(pids[index], PROC_PIDTBSDINFO, 0, &zero, (int)sizeof(zero));
        int zero_error = errno;
        errno = 0;
        int one_bytes = proc_pidinfo(pids[index], PROC_PIDTBSDINFO, 1, &one, (int)sizeof(one));
        int one_error = errno;
        bool valid = pids[index] > 0 && one_bytes == (int)sizeof(one)
            && one.pbi_pid == (uint32_t)pids[index] && one.pbi_pgid == (uint32_t)group;
        leader |= valid && pids[index] == group;
        zombies &= valid && one.pbi_status == SZOMB;
        printf("{\"requestedPID\":%d,\"arg0\":{\"bytes\":%d,\"errno\":%d,\"pid\":%u,\"pgid\":%u,\"status\":%u},"
               "\"arg1\":{\"bytes\":%d,\"errno\":%d,\"pid\":%u,\"pgid\":%u,\"status\":%u}}",
               pids[index], zero_bytes, zero_error, zero.pbi_pid, zero.pbi_pgid, zero.pbi_status,
               one_bytes, one_error, one.pbi_pid, one.pbi_pgid, one.pbi_status);
    }
    errno = 0;
    int second_bytes = proc_listpids(PROC_PGRP_ONLY, (uint32_t)group, second, (int)sizeof(second));
    int second_error = errno;
    bool stable = complete && second_bytes == bytes;
    if (stable) {
        qsort(pids, (size_t)count, sizeof(int), integer_order);
        qsort(second, (size_t)count, sizeof(int), integer_order);
        stable = memcmp(pids, second, (size_t)bytes) == 0;
        for (int index = 1; index < count; index++) if (pids[index] == pids[index - 1]) stable = false;
    }
    printf("],\"secondBytes\":%d,\"secondErrno\":%d,\"stable\":%s,\"leaderPresent\":%s,\"allZombies\":%s}",
           second_bytes, second_error, boolean(stable), boolean(leader), boolean(stable && leader && zombies));
}

static void sysctl_snapshot(pid_t group) {
    int names[] = {CTL_KERN, KERN_PROC, KERN_PROC_PGRP, group};
    size_t estimate = 0;
    errno = 0;
    int estimated = sysctl(names, 4, NULL, &estimate, NULL, 0), estimate_error = errno;
    size_t capacity = estimate + 16 * sizeof(struct kinfo_proc);
    bool bounded = estimated == 0 && estimate <= 1024 * 1024 && capacity <= 1024 * 1024;
    struct kinfo_proc *items = bounded ? calloc(1, capacity) : NULL;
    size_t bytes = capacity;
    int result = -1, failure = 0;
    if (items) { errno = 0; result = sysctl(names, 4, items, &bytes, NULL, 0); failure = errno; }
    bool complete = items && result == 0 && bytes > 0 && bytes <= capacity && bytes % sizeof(*items) == 0;
    size_t count = complete ? bytes / sizeof(*items) : 0;
    bool leader = false, zombies = complete;
    printf("\"sysctl\":{\"estimateResult\":%d,\"estimateErrno\":%d,\"estimatedBytes\":%zu,\"result\":%d,\"errno\":%d,\"bytes\":%zu,\"members\":[",
           estimated, estimate_error, estimate, result, failure, bytes);
    for (size_t index = 0; index < count; index++) {
        if (index) putchar(',');
        pid_t pid = items[index].kp_proc.p_pid, pgid = items[index].kp_eproc.e_pgid;
        int state = items[index].kp_proc.p_stat;
        leader |= pid == group && pgid == group;
        zombies &= pid > 0 && pgid == group && state == SZOMB;
        printf("{\"pid\":%d,\"pgid\":%d,\"status\":%d}", pid, pgid, state);
    }
    printf("],\"complete\":%s,\"leaderPresent\":%s,\"allZombies\":%s}",
           boolean(complete), boolean(leader), boolean(complete && leader && zombies));
    free(items);
}

static void ps_snapshot(pid_t group) {
    int pipes[2];
    if (pipe(pipes)) { printf("\"ps\":{\"pipeErrno\":%d}", errno); return; }
    posix_spawn_file_actions_t actions;
    if (posix_spawn_file_actions_init(&actions)) _exit(92);
    posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0);
    posix_spawn_file_actions_addopen(&actions, STDERR_FILENO, "/dev/null", O_WRONLY, 0);
    posix_spawn_file_actions_adddup2(&actions, pipes[1], STDOUT_FILENO);
    posix_spawn_file_actions_addclose(&actions, pipes[0]);
    posix_spawn_file_actions_addclose(&actions, pipes[1]);
    char *arguments[] = {"/bin/ps", "-axo", "pid=,pgid=,stat=", NULL};
    char *environment[] = {"PATH=/usr/bin:/bin", "LC_ALL=C", NULL};
    pid_t process = -1;
    int spawned = posix_spawn(&process, arguments[0], &actions, NULL, arguments, environment);
    posix_spawn_file_actions_destroy(&actions); close(pipes[1]);
    char *data = calloc(1, 1024 * 1024 + 1);
    size_t length = 0;
    bool eof = false, collected = false, exceeded = false;
    int status = -1;
    double deadline = monotonic() + 3;
    fcntl(pipes[0], F_SETFL, O_NONBLOCK);
    if (spawned == 0 && data) {
        while ((!eof || !collected) && monotonic() < deadline && !interrupted) {
            ssize_t amount = read(pipes[0], data + length, 1024 * 1024 - length);
            if (amount > 0) length += (size_t)amount;
            else if (amount == 0) eof = true;
            if (length == 1024 * 1024) { exceeded = true; break; }
            if (!collected) collected = waitpid(process, &status, WNOHANG) == process;
            if (!eof || !collected) { struct pollfd poller = {pipes[0], POLLIN, 0}; poll(&poller, 1, 10); }
        }
    }
    /* This is a direct, still-owned ps child. Never signal after wait collected it. */
    if (spawned == 0 && !collected) {
        kill(process, SIGKILL);
        while (waitpid(process, &status, 0) < 0 && errno == EINTR) {}
    }
    close(pipes[0]);
    printf("\"ps\":{\"spawnErrno\":%d,\"waitStatus\":%d,\"complete\":%s,\"bytes\":%zu,\"members\":[",
           spawned, status, boolean(spawned == 0 && eof && collected && !exceeded), length);
    bool first = true;
    if (data) {
        char *cursor = NULL;
        for (char *line = strtok_r(data, "\n", &cursor); line; line = strtok_r(NULL, "\n", &cursor)) {
            int pid = 0, pgid = 0; char state[32];
            if (sscanf(line, "%d %d %31s", &pid, &pgid, state) == 3 && pgid == group) {
                if (!first) putchar(',');
                first = false;
                printf("{\"pid\":%d,\"pgid\":%d,\"status\":\"%s\"}", pid, pgid, state);
            }
        }
        free(data);
    }
    printf("]}");
}

static void snapshot(pid_t group) {
    printf("{"); library_snapshot(group); putchar(','); sysctl_snapshot(group); putchar(','); ps_snapshot(group); printf("}");
}

struct identities { pid_t pid, pgid, sid, descendant; };

int main(int argc, char **argv) {
    if (argc != 2 || (strcmp(argv[1], "solo") && strcmp(argv[1], "live"))) return 2;
    bool live = strcmp(argv[1], "live") == 0;
    setvbuf(stdout, NULL, _IOLBF, 0);
    struct sigaction handler; memset(&handler, 0, sizeof(handler)); handler.sa_handler = interrupt_handler;
    sigaction(SIGINT, &handler, NULL); sigaction(SIGTERM, &handler, NULL);
    signal(SIGPIPE, SIG_IGN);
    int ready[2], command[2], liveness[2];
    if (pipe(ready) || pipe(command) || pipe(liveness)) return 3;
    for (int index = 0; index < 2; index++) {
        fcntl(ready[index], F_SETFD, FD_CLOEXEC); fcntl(command[index], F_SETFD, FD_CLOEXEC); fcntl(liveness[index], F_SETFD, FD_CLOEXEC);
    }
    pid_t leader = fork();
    if (leader < 0) return 4;
    if (leader == 0) {
        close(ready[0]); close(command[1]); close(liveness[0]);
        signal(SIGINT, SIG_IGN); signal(SIGTERM, SIG_IGN);
        if (setsid() < 0) _exit(93);
        struct identities identities = {getpid(), getpgrp(), getsid(0), 0};
        if (live) {
            identities.descendant = fork();
            if (identities.descendant < 0) _exit(94);
            if (identities.descendant == 0) {
                close(ready[1]); close(command[0]);
                alarm(25); /* Bounded synthetic descendant even if the controller crashes. */
                for (;;) pause();
            }
        }
        if (write(ready[1], &identities, sizeof(identities)) != (ssize_t)sizeof(identities)) _exit(95);
        close(ready[1]);
        char value;
        if (read(command[0], &value, 1) != 1) _exit(96);
        _exit(7);
    }
    close(ready[1]); close(command[0]); close(liveness[1]);
    struct identities identities;
    ssize_t read_count = read(ready[0], &identities, sizeof(identities)); close(ready[0]);
    bool owned = read_count == (ssize_t)sizeof(identities) && identities.pid == leader
        && identities.pgid == leader && identities.sid == leader;
    errno = 0;
    int queue = kqueue();
    struct kevent event; EV_SET(&event, (uintptr_t)leader, EVFILT_PROC, EV_ADD | EV_ONESHOT, NOTE_EXIT, 0, NULL);
    if (queue >= 0) errno = 0;
    int registered = queue >= 0 ? kevent(queue, &event, 1, NULL, 0, NULL) : -1;
    int registration_error = errno;
    char go = 'g'; (void)write(command[1], &go, 1); close(command[1]);
    struct timespec timeout = {5, 0};
    errno = 0;
    int observed = registered == 0 ? kevent(queue, NULL, 0, &event, 1, &timeout) : -1;
    int observation_error = errno;
    bool exited = observed == 1 && event.ident == (uintptr_t)leader && event.filter == EVFILT_PROC
        && (event.fflags & NOTE_EXIT) && !(event.flags & EV_ERROR);
    struct stat ps; memset(&ps, 0, sizeof(ps)); int ps_stat = stat("/bin/ps", &ps);
    printf("{\"event\":\"ready\",\"mode\":\"%s\",\"probePID\":%d,\"probePGID\":%d,\"leaderPID\":%d,\"leaderPGID\":%d,\"leaderSID\":%d,\"descendantPID\":%d,"
           "\"owned\":%s,\"registered\":%d,\"registrationErrno\":%d,\"observed\":%d,\"observationErrno\":%d,\"exitObservedWithoutReap\":%s,"
           "\"psStat\":{\"result\":%d,\"mode\":%u,\"uid\":%u,\"gid\":%u,\"setuid\":%s,\"setgid\":%s},"
           "\"sdk\":{\"procBSDInfoSize\":%zu,\"kinfoProcSize\":%zu,\"bsdStatusOffset\":%zu,\"bsdPGIDOffset\":%zu,\"zombieState\":%d},\"snapshot\":",
           argv[1], getpid(), getpgrp(), leader, owned ? identities.pgid : -1, owned ? identities.sid : -1,
           owned ? identities.descendant : -1, boolean(owned), registered, registration_error, observed, observation_error, boolean(exited),
           ps_stat, (unsigned)(ps.st_mode & 07777), ps.st_uid, ps.st_gid, boolean(ps.st_mode & S_ISUID), boolean(ps.st_mode & S_ISGID),
           sizeof(struct proc_bsdinfo), sizeof(struct kinfo_proc), offsetof(struct proc_bsdinfo, pbi_status), offsetof(struct proc_bsdinfo, pbi_pgid), SZOMB);
    snapshot(leader); printf("}\n");
    /* The outer controller may inspect this exact group while its leader is
       still our uncollected child. No signal/collection happens before ack. */
    struct pollfd input = {STDIN_FILENO, POLLIN, 0};
    int acknowledged = !interrupted && poll(&input, 1, 10000) > 0 && read(STDIN_FILENO, &go, 1) == 1 && go == 'g';
    errno = 0; int term = owned ? killpg(leader, SIGTERM) : kill(leader, SIGTERM); int term_error = errno;
    printf("{\"event\":\"after-term\",\"acknowledged\":%s,\"result\":%d,\"errno\":%d,\"snapshot\":", boolean(acknowledged), term, term_error);
    snapshot(leader); printf("}\n");
    errno = 0; int killed = owned ? killpg(leader, SIGKILL) : kill(leader, SIGKILL); int kill_error = errno;
    struct pollfd alive = {liveness[0], POLLIN | POLLHUP, 0};
    int ended = poll(&alive, 1, 3000) > 0 && read(liveness[0], &go, 1) == 0;
    close(liveness[0]);
    printf("{\"event\":\"after-kill\",\"result\":%d,\"errno\":%d,\"livenessPipeClosed\":%s,\"snapshot\":", killed, kill_error, boolean(ended));
    snapshot(leader); printf("}\n");
    int status = -1; pid_t collected;
    do { collected = waitpid(leader, &status, 0); } while (collected < 0 && errno == EINTR);
    if (queue >= 0) close(queue);
    printf("{\"event\":\"reaped\",\"pid\":%d,\"waitStatus\":%d,\"exitCode\":%d,\"signal\":%d,\"interrupted\":%d}\n",
           collected, status, WIFEXITED(status) ? WEXITSTATUS(status) : -1, WIFSIGNALED(status) ? WTERMSIG(status) : 0, interrupted);
    return owned && exited && acknowledged && collected == leader && ended ? 0 : 1;
}
