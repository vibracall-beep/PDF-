/* Local IPC diagnostic. Exit 0 reports an attempted operation, not approval.
 * All network endpoints belong to this process and use IPv4 loopback only.
 * The caller must reject incomplete/denied results except its specific EPERM
 * negative controls. A five-second hard deadline exits 124 without a report.
 */
#define _XOPEN_SOURCE 700
#include <sys/types.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

struct Result {
    int socketCreated, socketErrno, bound, bindErrno;
    int listening, listenErrno, connected, connectErrno;
    int exchanged, exchangeErrno;
};

static void deadline(int signal_number) {
    (void)signal_number;
    _exit(124);
}

static int report(const struct Result *r) {
    printf("{\"socketCreated\":%s,\"socketErrno\":%d,"
           "\"bound\":%s,\"bindErrno\":%d,"
           "\"listening\":%s,\"listenErrno\":%d,"
           "\"connected\":%s,\"connectErrno\":%d,"
           "\"exchanged\":%s,\"exchangeErrno\":%d}\n",
           r->socketCreated ? "true" : "false", r->socketErrno,
           r->bound ? "true" : "false", r->bindErrno,
           r->listening ? "true" : "false", r->listenErrno,
           r->connected ? "true" : "false", r->connectErrno,
           r->exchanged ? "true" : "false", r->exchangeErrno);
    return fflush(stdout) == 0 ? 0 : 2;
}

static int pair(int family, int type, int *server, int *client, struct Result *r) {
    *server = socket(family, type, 0);
    if (*server < 0) { r->socketErrno = errno; return 0; }
    *client = socket(family, type, 0);
    if (*client < 0) { r->socketErrno = errno; return 0; }
    r->socketCreated = 1;
    return 1;
}

static int one_byte_send(int fd, unsigned char value) {
    ssize_t n = send(fd, &value, 1, 0);
    if (n == 1) return 1;
    if (n >= 0) errno = EIO;
    return 0;
}

static int one_byte_receive(int fd, unsigned char expected) {
    unsigned char actual = 0;
    ssize_t n = recv(fd, &actual, 1, 0);
    if (n == 1 && actual == expected) return 1;
    if (n >= 0) errno = EPROTO;
    return 0;
}

static void stream_exchange(int server, int client, struct Result *r) {
    int accepted = accept(server, NULL, NULL);
    if (accepted < 0) { r->exchangeErrno = errno; return; }
    if (one_byte_send(client, 0x51) && one_byte_receive(accepted, 0x51)
        && one_byte_send(accepted, 0xA6) && one_byte_receive(client, 0xA6))
        r->exchanged = 1;
    else r->exchangeErrno = errno;
    close(accepted);
}

/* Resolve the parent only, permitting normal /var -> /private/var aliases on
 * macOS. The leaf is never resolved or removed if it already exists. bind()
 * receives the canonical parent path; the parent must be caller-owned/private.
 */
static int unix_parent(const char *requested, char *canonical, size_t capacity,
                       int *directory, char *leaf, size_t leaf_capacity, int office) {
    char parent[PATH_MAX], resolved[PATH_MAX];
    if (!requested || requested[0] != '/' || strlen(requested) >= sizeof(parent))
        return 0;
    const char *slash = strrchr(requested, '/');
    size_t name_length = strlen(slash + 1), parent_length = (size_t)(slash - requested);
    if (!name_length || name_length >= leaf_capacity
        || !strcmp(slash + 1, ".") || !strcmp(slash + 1, "..")) return 0;
    memcpy(leaf, slash + 1, name_length + 1);
    if (!parent_length) { parent[0] = '/'; parent[1] = '\0'; }
    else { memcpy(parent, requested, parent_length); parent[parent_length] = '\0'; }
    if (!realpath(parent, resolved)) return 0;
    *directory = open(resolved, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (*directory < 0) return 0;
    struct stat directory_info, existing;
    if (fstat(*directory, &directory_info) || !S_ISDIR(directory_info.st_mode)) return 0;
    if (office) {
        char temporary[PATH_MAX], prefix[96];
        if (!realpath("/tmp", temporary) || strcmp(resolved, temporary)) return 0;
        /* This explicit diagnostic mode models LibreOffice's literal socket
         * in the system temporary directory, never an arbitrary public path. */
        if ((directory_info.st_mode & 0022) && !(directory_info.st_mode & S_ISVTX)) return 0;
        int prefix_length = snprintf(prefix, sizeof(prefix), "OSL_PIPE_%lu_SingleOfficeIPC_",
                                     (unsigned long)geteuid());
        if (prefix_length <= 0 || (size_t)prefix_length >= sizeof(prefix)
            || strncmp(leaf, prefix, (size_t)prefix_length)) return 0;
        const char *hash = leaf + prefix_length;
        size_t hash_length = strlen(hash);
        if (hash_length < 16 || hash_length > 32) return 0;
        for (size_t i = 0; i < hash_length; ++i)
            if (!((hash[i] >= '0' && hash[i] <= '9') || (hash[i] >= 'a' && hash[i] <= 'f')))
                return 0;
    } else if (directory_info.st_uid != geteuid() || (directory_info.st_mode & 0077)) return 0;
    if (fstatat(*directory, leaf, &existing, AT_SYMLINK_NOFOLLOW) == 0 || errno != ENOENT)
        return 0;
    int length = snprintf(canonical, capacity, "%s/%s", resolved, leaf);
    return length > 0 && (size_t)length < capacity;
}

static int unix_probe(const char *path, int office) {
    struct Result r = {0};
    struct sockaddr_un address;
    struct stat owned, current;
    char leaf[NAME_MAX + 1];
    int directory = -1, server = -1, client = -1, owns_node = 0, cleanup_ok = 1;
    memset(&address, 0, sizeof(address));
    if (!unix_parent(path, address.sun_path, sizeof(address.sun_path),
                     &directory, leaf, sizeof(leaf), office)) {
        if (directory >= 0) close(directory);
        fputs("Invalid or non-private Unix socket destination.\n", stderr);
        return 2;
    }
    address.sun_family = AF_UNIX;
    socklen_t length = (socklen_t)(offsetof(struct sockaddr_un, sun_path)
                                  + strlen(address.sun_path) + 1);
#ifdef __APPLE__
    address.sun_len = (unsigned char)length;
#endif
    if (!pair(AF_UNIX, SOCK_STREAM, &server, &client, &r)) goto done;
    if (bind(server, (struct sockaddr *)&address, length)) {
        r.bindErrno = errno; goto done;
    }
    r.bound = 1;
    if (fstatat(directory, leaf, &owned, AT_SYMLINK_NOFOLLOW) || !S_ISSOCK(owned.st_mode)) {
        cleanup_ok = 0; goto done;
    }
    owns_node = 1;
    if (listen(server, 1)) { r.listenErrno = errno; goto done; }
    r.listening = 1;
    if (connect(client, (struct sockaddr *)&address, length)) {
        r.connectErrno = errno; goto done;
    }
    r.connected = 1;
    stream_exchange(server, client, &r);
done:
    if (client >= 0) close(client);
    if (server >= 0) close(server);
    if (owns_node) {
        if (fstatat(directory, leaf, &current, AT_SYMLINK_NOFOLLOW)
            || !S_ISSOCK(current.st_mode) || current.st_dev != owned.st_dev
            || current.st_ino != owned.st_ino || unlinkat(directory, leaf, 0)) cleanup_ok = 0;
    }
    close(directory);
    if (!cleanup_ok) {
        fputs("Unix socket identity or cleanup failed.\n", stderr);
        return 2;
    }
    return report(&r);
}

static int internet_probe(int datagram) {
    struct Result r = {0};
    int server = -1, client = -1;
    struct sockaddr_in address;
    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    address.sin_port = 0;
#ifdef __APPLE__
    address.sin_len = sizeof(address);
#endif
    if (!pair(AF_INET, datagram ? SOCK_DGRAM : SOCK_STREAM, &server, &client, &r)) goto done;
    if (bind(server, (struct sockaddr *)&address, sizeof(address))) {
        r.bindErrno = errno; goto done;
    }
    r.bound = 1;
    socklen_t length = sizeof(address);
    if (getsockname(server, (struct sockaddr *)&address, &length)
        || length != sizeof(address) || address.sin_family != AF_INET
        || address.sin_addr.s_addr != htonl(INADDR_LOOPBACK) || address.sin_port == 0) {
        r.exchangeErrno = EPROTO; goto done;
    }
    if (!datagram) {
        if (listen(server, 1)) { r.listenErrno = errno; goto done; }
        r.listening = 1;
    }
    if (connect(client, (struct sockaddr *)&address, sizeof(address))) {
        r.connectErrno = errno; goto done;
    }
    r.connected = 1;
    if (!datagram) stream_exchange(server, client, &r);
    else {
        struct sockaddr_in peer, client_address;
        socklen_t peer_length = sizeof(peer), client_length = sizeof(client_address);
        unsigned char value = 0;
        memset(&peer, 0, sizeof(peer)); memset(&client_address, 0, sizeof(client_address));
        if (getsockname(client, (struct sockaddr *)&client_address, &client_length)) {
            r.exchangeErrno = errno; goto done;
        }
        if (client_length != sizeof(client_address) || client_address.sin_family != AF_INET
            || client_address.sin_addr.s_addr != htonl(INADDR_LOOPBACK)
            || client_address.sin_port == 0) { r.exchangeErrno = EPROTO; goto done; }
        if (!one_byte_send(client, 0x51)) { r.exchangeErrno = errno; goto done; }
        ssize_t n = recvfrom(server, &value, 1, 0, (struct sockaddr *)&peer, &peer_length);
        if (n < 0) { r.exchangeErrno = errno; goto done; }
        if (n != 1 || value != 0x51 || peer_length != sizeof(peer) || peer.sin_family != AF_INET
            || peer.sin_addr.s_addr != client_address.sin_addr.s_addr
            || peer.sin_port != client_address.sin_port) { r.exchangeErrno = EPROTO; goto done; }
        value = 0xA6;
        n = sendto(server, &value, 1, 0, (struct sockaddr *)&client_address, sizeof(client_address));
        if (n != 1) { r.exchangeErrno = n < 0 ? errno : EIO; goto done; }
        if (one_byte_receive(client, 0xA6)) r.exchanged = 1;
        else r.exchangeErrno = errno;
    }
done:
    if (client >= 0) close(client);
    if (server >= 0) close(server);
    return report(&r);
}

int main(int argc, char **argv) {
    struct sigaction action;
    memset(&action, 0, sizeof(action));
    action.sa_handler = deadline;
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGALRM, &action, NULL) || signal(SIGPIPE, SIG_IGN) == SIG_ERR) return 2;
    alarm(5);
    if (argc == 3 && !strcmp(argv[1], "unix")) return unix_probe(argv[2], 0);
    if (argc == 3 && !strcmp(argv[1], "unix-office")) return unix_probe(argv[2], 1);
    if (argc == 2 && !strcmp(argv[1], "tcp")) return internet_probe(0);
    if (argc == 2 && !strcmp(argv[1], "udp")) return internet_probe(1);
    fputs("Usage: probe unix ABSOLUTE_PATH | probe unix-office OFFICE_PATH | probe tcp | probe udp\n", stderr);
    return 2;
}
