#include "junction/syscall/seccomp.h"

#include <errno.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>

extern "C" {
#include <base/signal.h>
}

#include "junction/kernel/ksys.h"
#include "junction/kernel/proc.h"
#include "junction/syscall/entry.h"
#include "junction/syscall/seccomp_bpf.h"
#include "junction/syscall/syscall.h"
#include "junction/syscall/systbl.h"

namespace junction {

/* Source: https://outflux.net/teach-seccomp/step-3/example.c
 * List of syscall numbers: https://filippo.io/linux-syscall-table/
 */
Status<void> _install_seccomp_filter() {
  struct sock_filter filter[] = {
      /* List allowed syscalls. */
      ALLOW_CALADAN_SYSCALL(ioctl),
      ALLOW_CALADAN_SYSCALL(rt_sigreturn),
      ALLOW_CALADAN_SYSCALL(mmap),
      ALLOW_CALADAN_SYSCALL(madvise),
      ALLOW_CALADAN_SYSCALL(mprotect),
      ALLOW_CALADAN_SYSCALL(exit_group),
      ALLOW_CALADAN_SYSCALL(write),

      ALLOW_SYSCALL(gettimeofday),
      ALLOW_SYSCALL(fstat),
      ALLOW_SYSCALL(stat),
      ALLOW_SYSCALL(brk),
      ALLOW_SYSCALL(munmap),
      ALLOW_SYSCALL(getcwd),
      ALLOW_SYSCALL(readlink),
      ALLOW_SYSCALL(readlink),
      ALLOW_SYSCALL(prlimit64),
      ALLOW_SYSCALL(sysinfo),
      ALLOW_SYSCALL(fcntl),
      ALLOW_SYSCALL(geteuid),
      ALLOW_SYSCALL(getegid),
      ALLOW_SYSCALL(getgid),
      ALLOW_SYSCALL(rename),
      ALLOW_SYSCALL(madvise),
      ALLOW_SYSCALL(restart_syscall),
      ALLOW_SYSCALL(clock_nanosleep),
      ALLOW_SYSCALL(getppid),
      ALLOW_SYSCALL(getuid),
      ALLOW_SYSCALL(gettid),
      ALLOW_SYSCALL(access),
      ALLOW_SYSCALL(time),

      ALLOW_JUNCTION_SYSCALL(ioctl),
      ALLOW_JUNCTION_SYSCALL(prctl),
      ALLOW_JUNCTION_SYSCALL(getdents),
      ALLOW_JUNCTION_SYSCALL(getdents64),
      ALLOW_JUNCTION_SYSCALL(newfstatat),
      ALLOW_JUNCTION_SYSCALL(mmap),
      ALLOW_JUNCTION_SYSCALL(mprotect),
      ALLOW_JUNCTION_SYSCALL(fsync),
      ALLOW_JUNCTION_SYSCALL(openat),
      ALLOW_JUNCTION_SYSCALL(open),
      ALLOW_JUNCTION_SYSCALL(close),
      ALLOW_JUNCTION_SYSCALL(read),
      ALLOW_JUNCTION_SYSCALL(pread64),
      ALLOW_JUNCTION_SYSCALL(pwrite64),
      ALLOW_JUNCTION_SYSCALL(write),
      ALLOW_JUNCTION_SYSCALL(clock_gettime),
      ALLOW_JUNCTION_SYSCALL(writev),
      ALLOW_JUNCTION_SYSCALL(exit_group),
      // TODO(girfan): Remove after merging VFS changes
      ALLOW_JUNCTION_SYSCALL(mkdir),

      TRAP,
  };
  struct sock_fprog prog = {
      .len = (unsigned short)(sizeof(filter) / sizeof(filter[0])),
      .filter = filter,
  };

  if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)) {
    perror("prctl(NO_NEW_PRIVS)");
    if (errno == EINVAL) {
      fprintf(stderr, "SECCOMP_FILTER is not available. :(\n");
    }
    return MakeError(-errno);
  }

  int rv = syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER,
                   SECCOMP_FILTER_FLAG_TSYNC, &prog);
  if (rv) {
    perror("syscall(SECCOMP_SET_MODE_FILTER)");
    return MakeError(rv);
  }

  return {};
}

void log_syscall_msg(const char* msg_needed, long sysn) {
  char buf[128], *pos;
  memcpy(buf, msg_needed, strlen(msg_needed));
  pos = buf + strlen(msg_needed);
  *pos++ = ' ';
  *pos++ = '(';
  size_t slen = strlen(syscall_names[sysn]);
  // This will likely cause a segfault instead of printing
  BUG_ON(pos - buf + slen + 2 > sizeof(buf));
  memcpy(pos, syscall_names[sysn], slen);
  pos += slen;
  *pos++ = ')';
  *pos++ = '\n';
  ksys_write(STDOUT_FILENO, buf, pos - buf);
}

static __attribute__((__optimize__("-fno-stack-protector"))) void
__signal_handler(int nr, siginfo_t* info, void* void_context) {
  ucontext_t* ctx = reinterpret_cast<ucontext_t*>(void_context);

  if (unlikely(info->si_code != SYS_SECCOMP)) return;
  if (unlikely(!ctx)) return;

  long sysn = static_cast<long>(ctx->uc_mcontext.gregs[REG_SYSCALL]);

  if (unlikely(!thread_self())) {
    log_syscall_msg("Unexpected syscall from Caladan", sysn);
    syscall_exit(-1);
  }

  if (unlikely(!get_uthread_specific())) {
    log_syscall_msg("Intercepted syscall originating in junction", sysn);
    syscall_exit(-1);
  }

  // redirect to syscall handler that will save state for us
  ctx->uc_mcontext.gregs[REG_RIP] =
      reinterpret_cast<uint64_t>(junction_syscall_full_trap);
}

Status<void> _install_signal_handler() {
  struct sigaction act;

  if (sigemptyset(&act.sa_mask) != 0) return MakeError(-errno);

  act.sa_sigaction = &__signal_handler;
  act.sa_flags = SA_SIGINFO | SA_NODEFER | SA_ONSTACK;

  if (base_sigaction(SIGSYS, &act, NULL) < 0) {
    perror("sigaction");
    return MakeError(-errno);
  }

  return {};
}

Status<void> init_seccomp() {
  // Install signal handlers for syscalls
  Status<void> ret = _install_signal_handler();
  if (!ret) return ret;

  // Install syscall filter.
  return _install_seccomp_filter();
}

}  // namespace junction
