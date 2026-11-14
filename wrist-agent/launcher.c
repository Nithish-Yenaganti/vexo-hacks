/* Wrist Agent.app's main program.
 *
 * macOS gives Screen Recording, Accessibility and Bluetooth to the app that asks. A shell
 * script as the app's program shows up as /bin/bash, so permissions never match the app.
 * This small compiled launcher IS the app: it starts Python as its child (not exec), so
 * every request from Python is made on behalf of "Wrist Agent".
 *
 * Built by `wrist` with:  clang -O2 -o ".../MacOS/wrist-agent" launcher.c
 * -DROOT=... is the project folder, -DLOG=... the log file.
 */
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <sys/wait.h>
#include <unistd.h>
#include <fcntl.h>

#ifndef ROOT
#error "build with -DROOT=\"/path/to/vexo-hacks\""
#endif
#ifndef LOG
#error "build with -DLOG=\"/path/to/WristAgent.log\""
#endif

extern char **environ;
static pid_t child = 0;

static void forward(int sig) {
    if (child > 0) kill(child, sig);
}

int main(void) {
    if (chdir(ROOT) != 0) { perror("chdir"); return 1; }
    posix_spawn_file_actions_t io;
    posix_spawn_file_actions_init(&io);
    posix_spawn_file_actions_addopen(&io, 1, LOG, O_WRONLY | O_CREAT | O_APPEND, 0644);
    posix_spawn_file_actions_adddup2(&io, 1, 2);
    char *argv[] = {ROOT "/.venv/bin/python", ROOT "/wrist-agent/app.py", NULL};
    if (posix_spawn(&child, argv[0], &io, NULL, argv, environ) != 0) { perror("spawn"); return 1; }
    signal(SIGTERM, forward);
    signal(SIGINT, forward);
    int status = 0;
    while (waitpid(child, &status, 0) < 0) {}
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
