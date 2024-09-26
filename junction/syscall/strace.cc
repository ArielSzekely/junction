#include "junction/syscall/strace.h"

extern "C" {
#include <linux/futex.h>
#include <sched.h>
#include <signal.h>
}

#include <map>

#include "junction/bindings/log.h"

#ifndef CLONE_CLEAR_SIGHAND
#define CLONE_CLEAR_SIGHAND 0x100000000ULL
#endif

#ifndef CLONE_INTO_CGROUP
#define CLONE_INTO_CGROUP 0x200000000ULL
#endif

namespace junction {

namespace strace {
const std::map<int, std::string> protection_flags{
    {PROT_READ, "PROT_READ"},
    {PROT_WRITE, "PROT_WRITE"},
    {PROT_EXEC, "PROT_EXEC"},
};

const std::map<int, std::string> mmap_flags{
    {MAP_SHARED, "MAP_SHARED"},
    {MAP_PRIVATE, "MAP_PRIVATE"},
    {MAP_ANONYMOUS, "MAP_ANONYMOUS"},
    {MAP_FIXED, "MAP_FIXED"},
    {MAP_FIXED_NOREPLACE, "MAP_FIXED_NOREPLACE"},
    {MAP_GROWSDOWN, "MAP_GROWSDOWN"},
    {MAP_HUGETLB, "MAP_HUGETLB"},
    {MAP_LOCKED, "MAP_LOCKED"},
    {MAP_NONBLOCK, "MAP_NONBLOCK"},
    {MAP_NORESERVE, "MAP_NORESERVE"},
    {MAP_POPULATE, "MAP_POPULATE"},
    {MAP_STACK, "MAP_STACK"},
};

const std::map<int, std::string> open_flags{
    {O_APPEND, "O_APPEND"},       {O_ASYNC, "O_ASYNC"},
    {O_CLOEXEC, "O_CLOEXEC"},     {O_CREAT, "O_CREAT"},
    {O_DIRECT, "O_DIRECT"},       {O_DIRECTORY, "O_DIRECTORY"},
    {O_DSYNC, "O_DSYNC"},         {O_EXCL, "O_EXCL"},
    {O_LARGEFILE, "O_LARGEFILE"}, {O_NOATIME, "O_NOATIME"},
    {O_NOCTTY, "O_NOCTTY"},       {O_NOFOLLOW, "O_NOFOLLOW"},
    {O_NONBLOCK, "O_NONBLOCK"},   {O_PATH, "O_PATH"},
    {O_SYNC, "O_SYNC"},           {O_TMPFILE, "O_TMPFILE"},
    {O_TRUNC, "O_TRUNC"},         {O_WRONLY, "O_WRONLY"},
    {O_RDWR, "O_RDWR"},
};

const std::map<int, std::string> madvise_hints{
    {MADV_NORMAL, "MADV_NORMAL"},
    {MADV_DONTNEED, "MADV_DONTNEED"},
    {MADV_RANDOM, "MADV_RANDOM"},
    {MADV_REMOVE, "MADV_REMOVE"},
    {MADV_SEQUENTIAL, "MADV_SEQUENTIAL"},
    {MADV_DONTFORK, "MADV_DONTFORK"},
    {MADV_WILLNEED, "MADV_WILLNEED"},
    {MADV_DOFORK, "MADV_DOFORK"},
    {MADV_HUGEPAGE, "MADV_HUGEPAGE"},
    {MADV_HWPOISON, "MADV_HWPOISON"},
    {MADV_NOHUGEPAGE, "MADV_NOHUGEPAGE"},
    {MADV_MERGEABLE, "MADV_MERGEABLE"},
    {MADV_COLLAPSE, "MADV_COLLAPSE"},
    {MADV_UNMERGEABLE, "MADV_UNMERGEABLE"},
    {MADV_DONTDUMP, "MADV_DONTDUMP"},
    {MADV_DODUMP, "MADV_DODUMP"},
    {MADV_FREE, "MADV_FREE"},
    {MADV_WIPEONFORK, "MADV_WIPEONFORK"},
    {MADV_COLD, "MADV_COLD"},
    {MADV_PAGEOUT, "MADV_PAGEOUT"},
    {MADV_POPULATE_READ, "MADV_POPULATE_READ"},
    {MADV_POPULATE_WRITE, "MADV_POPULATE_WRITE"},
};

const std::map<int, std::string> clone_flags{
    {CLONE_CHILD_CLEARTID, "CLONE_CHILD_CLEARTID"},
    {CLONE_CHILD_SETTID, "CLONE_CHILD_SETTID"},
    {CLONE_CLEAR_SIGHAND, "CLONE_CLEAR_SIGHAND"},
    {CLONE_DETACHED, "CLONE_DETACHED"},
    {CLONE_FILES, "CLONE_FILES"},
    {CLONE_FS, "CLONE_FS"},
    {CLONE_INTO_CGROUP, "CLONE_INTO_CGROUP"},
    {CLONE_IO, "CLONE_IO"},
    {CLONE_NEWCGROUP, "CLONE_NEWCGROUP"},
    {CLONE_NEWIPC, "CLONE_NEWIPC"},
    {CLONE_NEWNET, "CLONE_NEWNET"},
    {CLONE_NEWNS, "CLONE_NEWNS"},
    {CLONE_NEWPID, "CLONE_NEWPID"},
    {CLONE_NEWUSER, "CLONE_NEWUSER"},
    {CLONE_NEWUTS, "CLONE_NEWUTS"},
    {CLONE_PARENT, "CLONE_PARENT"},
    {CLONE_PARENT_SETTID, "CLONE_PARENT_SETTID"},
    {CLONE_PIDFD, "CLONE_PIDFD"},
    {CLONE_PTRACE, "CLONE_PTRACE"},
    {CLONE_SETTLS, "CLONE_SETTLS"},
    {CLONE_SIGHAND, "CLONE_SIGHAND"},
    {CLONE_SYSVSEM, "CLONE_SYSVSEM"},
    {CLONE_THREAD, "CLONE_THREAD"},
    {CLONE_UNTRACED, "CLONE_UNTRACED"},
    {CLONE_VFORK, "CLONE_VFORK"},
    {CLONE_VM, "CLONE_VM"},
};

const std::map<int, std::string> futex_flags{
    {FUTEX_WAKE_BITSET, "FUTEX_WAKE_BITSET"},
    {FUTEX_WAIT, "FUTEX_WAIT"},
    {FUTEX_WAKE, "FUTEX_WAKE"},
    {FUTEX_FD, "FUTEX_FD"},
    {FUTEX_REQUEUE, "FUTEX_REQUEUE"},
    {FUTEX_CMP_REQUEUE, "FUTEX_CMP_REQUEUE"},
    {FUTEX_WAKE_OP, "FUTEX_WAKE_OP"},
    {FUTEX_WAIT_BITSET, "FUTEX_WAIT_BITSET"},
    {FUTEX_LOCK_PI, "FUTEX_LOCK_PI"},
    {FUTEX_LOCK_PI2, "FUTEX_LOCK_PI2"},
    {FUTEX_TRYLOCK_PI, "FUTEX_TRYLOCK_PI"},
    {FUTEX_UNLOCK_PI, "FUTEX_UNLOCK_PI"},
    {FUTEX_CMP_REQUEUE_PI, "FUTEX_CMP_REQUEUE_PI"},
    {FUTEX_WAIT_REQUEUE_PI, "FUTEX_WAIT_REQUEUE_PI"},
};

const char *sigmap[] = {
    "SIGHUP",  "SIGINT",    "SIGQUIT", "SIGILL",    "SIGTRAP", "SIGABRT",
    "SIGBUS",  "SIGFPE",    "SIGKILL", "SIGUSR1",   "SIGSEGV", "SIGUSR2",
    "SIGPIPE", "SIGALRM",   "SIGTERM", "SIGSTKFLT", "SIGCHLD", "SIGCONT",
    "SIGSTOP", "SIGTSTP",   "SIGTTIN", "SIGTTOU",   "SIGURG",  "SIGXCPU",
    "SIGXFSZ", "SIGVTALRM", "SIGPROF", "SIGWINCH",  "SIGIO",   "SIGPWR",
    "SIGSYS",  "SIGUNUSED"};

void PrintArg(int advice, MAdviseHint, rt::Logger &ss) {
  if (madvise_hints.count(advice))
    ss << madvise_hints.at(advice);
  else
    ss << advice;
}

void PrintArg(int signo, SignalNumber, rt::Logger &ss) {
  ss << sigmap[signo - 1];
}

void PrintArg(const char *arg, PathName *, rt::Logger &ss) {
  ss << "\"" << arg << "\"";
}

void PrintArg(int fd, AtFD, rt::Logger &ss) {
  if (fd == AT_FDCWD)
    ss << "AT_FDCWD";
  else
    ss << fd;
}

bool PrintArr(const std::map<int, std::string> &map, int flags,
              rt::Logger &ss) {
  bool done_one = false;
  for (const auto &[flag, name] : map) {
    if (!(flags & flag)) continue;
    if (!done_one)
      done_one = true;
    else
      ss << "|";
    ss << name;
  }
  return done_one;
}

void PrintArg(int prot, ProtFlag, rt::Logger &ss) {
  if (prot == PROT_NONE) {
    ss << "PROT_NONE";
    return;
  }
  PrintArr(protection_flags, prot, ss);
}

void PrintArg(int op, FutexOp, rt::Logger &ss) {
  int cmd = op & FUTEX_CMD_MASK;
  auto it = futex_flags.find(cmd);
  if (it != futex_flags.end())
    ss << it->second;
  else
    ss << cmd;

  if (op & FUTEX_PRIVATE_FLAG) ss << "|FUTEX_PRIVATE_FLAG";
  if (op & FUTEX_CLOCK_REALTIME) ss << "|FUTEX_CLOCK_REALTIME";
}

void PrintArg(int flags, MMapFlag, rt::Logger &ss) {
  PrintArr(mmap_flags, flags, ss);
}

void PrintArg(unsigned long flags, CloneFlag, rt::Logger &ss) {
  PrintArr(clone_flags, flags, ss);
}

void PrintArg(int flags, OpenFlag, rt::Logger &ss) {
  bool done_one = PrintArr(open_flags, flags, ss);
  if ((flags & (O_WRONLY | O_RDWR)) == 0) {
    if (done_one) ss << "|";
    ss << "O_RDONLY";
  }
}

void PrintArg(int *fds, FDPair *, rt::Logger &ss) {
  ss << "[" << fds[0] << ", " << fds[1] << "]";
}

}  // namespace strace

void LogSignal(const siginfo_t &info) {
  const char *signame;
  if (info.si_signo > 0 && info.si_signo < 32)
    signame = strace::sigmap[info.si_signo - 1];
  else
    signame = "unknown";

  LOG(INFO) << "[" << myproc().get_pid() << ":" << mythread().get_tid()
            << "] --- " << signame << " {si_signo=" << info.si_signo
            << ", si_code = " << info.si_code << ", si_addr = " << info.si_addr
            << "} ---";
}
}  // namespace junction
