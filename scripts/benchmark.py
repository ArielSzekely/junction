#!/usr/bin/python3

import stat
import os
import atexit
import sys
from datetime import datetime
from collections import defaultdict
import json
import subprocess
import time

import matplotlib as mpl
mpl.use('Agg')
import matplotlib.pyplot as plt

SCRIPT_DIR = os.path.split(os.path.realpath(__file__))[0]
ROOT_DIR = os.path.split(SCRIPT_DIR)[0] #f"{SCRIPT_DIR}/.."
BUILD_DIR = f"{ROOT_DIR}/build"
BIN_DIR = f"{ROOT_DIR}/bin"
JRUN = f"{BUILD_DIR}/junction/junction_run"
CONFIG = f"{BUILD_DIR}/junction/caladan_test_ts_st.config"
CALADAN_DIR = f"{ROOT_DIR}/lib/caladan"
CHROOT_DIR=f"{ROOT_DIR}/chroot"

LINUX_BASELINE = True
USE_CHROOT = True
ENABLE_ELF_BASELINE = True
ENABLE_JIF_USERSPACE_BASELINE = True
DO_KERNEL_EXPS = True
DO_KERNEL_NO_PREFETCH_EXP = True
DO_KERNEL_PREFETCH_EXP = True
DO_KERNEL_PREFETCH_REORDER_EXP = True
REDO_SNAPSHOT = True
DROPCACHE = 4

FBENCH = ["chameleon", "float_operation", "pyaes", "matmul", "json_serdes", "video_processing"]
FBENCH += ["lr_training", "image_processing", "linpack"]

RESIZERS = [
	("java", f"/usr/bin/java -cp {ROOT_DIR}/build/junction/samples/snapshots/java/jna-5.14.0.jar {ROOT_DIR}/build/junction/samples/snapshots/java/Resizer.java"),
	("rust", f"{ROOT_DIR}/build/junction/samples/snapshots/rust/resize-rs"),
	("go", f"{ROOT_DIR}/build/junction/samples/snapshots/go/resizer"),
]

IMAGES = [
	("large", f"{ROOT_DIR}/build/junction/samples/snapshots/images/IMG_4011.jpg"),
	("tiny", f"{ROOT_DIR}/build/junction/samples/snapshots/thumbnails/IMG_4011.jpg"),
]

def run(cmd):
	print(cmd)
	sys.stdout.flush()
	subprocess.check_output(cmd, shell=True)

def run_async(cmd):
	print(cmd)
	sys.stdout.flush()
	return subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE)

def kill_iok():
	run("sudo pkill iokerneld || true")

def run_iok():
	if os.system("pgrep iok > /dev/null") == 0:
		return
	run(f"sudo {CALADAN_DIR}/scripts/setup_machine.sh nouintr")
	run(f"sudo {CALADAN_DIR}/iokerneld ias nobw noht no_hw_qdel numanode -1 -- --allow 00:00.0 --vdev=net_tap0 > /tmp/iokernel0.log 2>&1 &")
	while os.system("grep -q 'running dataplan' /tmp/iokernel0.log") != 0:
		time.sleep(0.3)
		run("pgrep iokerneld > /dev/null")

def kill_chroot():
	run(f"sudo umount {CHROOT_DIR}/{BIN_DIR}")
	run(f"sudo umount {CHROOT_DIR}/{BUILD_DIR}")
	if jifpager_installed():
		run(f"sudo rm {CHROOT_DIR}/dev/jif_pager")

def setup_chroot():
	if not USE_CHROOT: return
	run(f"sudo mkdir -p {CHROOT_DIR}/{BIN_DIR} {CHROOT_DIR}/{BUILD_DIR}")
	run(f"sudo mount --bind -o ro {BIN_DIR} {CHROOT_DIR}/{BIN_DIR}")
	run(f"sudo mount --bind -o ro {BUILD_DIR} {CHROOT_DIR}/{BUILD_DIR}")

	if jifpager_installed():
		st = os.stat("/dev/jif_pager")
		major = os.major(st.st_rdev)
		minor = os.minor(st.st_rdev)

		run(f"sudo mknod -m 666 {CHROOT_DIR}/dev/jif_pager c {major} {minor} || true")

	atexit.register(kill_chroot)

def jifpager_installed():
	try:
		return DO_KERNEL_EXPS and stat.S_ISCHR(os.stat("/dev/jif_pager").st_mode)
	except:
		return False

def snapshot_elf(cmd, output_image, output_log, extra_flags = "", stop_count = 1):
	run(f"sudo -E {JRUN} {CONFIG} {extra_flags} -S {stop_count} --snapshot-prefix {output_image} -- {cmd} >> {output_log}_snapelf 2>&1")

def snapshot_jif(cmd, output_image, output_log, extra_flags = "", stop_count = 1):
	run(f"sudo -E {JRUN} {CONFIG} {extra_flags} --jif -S {stop_count} --madv_remap --snapshot-prefix {output_image} -- {cmd} >> {output_log}_snapjif 2>&1")

def restore_elf(image, output_log, extra_flags = ""):
	run(f"sudo -E {JRUN} {CONFIG} {extra_flags} -r -- {image}.metadata {image}.elf >> {output_log}_elf 2>&1")

def process_itree(output_image, output_log):
	run(f"stdbuf -e0 -i0 -o0 {BUILD_DIR}/jiftool {output_image}.jif {output_image}_itrees.jif build-itrees >> {output_log}_builditree 2>&1")

def process_fault_order(output_image, output_log):
	# add ordering to jif
	run(f"stdbuf -e0 -i0 -o0 {BUILD_DIR}/jiftool {output_image}_itrees.jif {output_image}_itrees_ord_reorder.jif add-ord --setup-prefetch {output_image}.ord >> {output_log}_addord 2>&1 ")
	run(f"stdbuf -e0 -i0 -o0 {BUILD_DIR}/jiftool {output_image}_itrees.jif {output_image}_itrees_ord.jif add-ord {output_image}.ord >> {output_log}_addord 2>&1 ")

def restore_jif(image, output_log, extra_flags = ""):
	run(f"sudo -E {JRUN} {CONFIG} {extra_flags} --jif -r -- {image}.jm {image}.jif >> {output_log}_jif 2>&1")

def restore_itrees_jif(image, output_log, extra_flags = "", reorder=False):
	run(f"sudo -E {JRUN} {CONFIG} {extra_flags} --jif -r -- {image}.jm {image}_itrees{"_ord_reorder" if reorder else ""}.jif >> {output_log}_itrees_jif 2>&1")

def jifpager_restore_itrees(image, output_log, cold=False, minor=False, fault_around=True, measure_latency=False, prefault=False, readahead=True, extra_flags = "", reorder=True, second_app=None):
	set_fault_around(1 if fault_around else 0)
	set_prefault(1 if prefault else 0)
	set_prefault_minor(1 if minor else 0)
	set_measure_latency(1 if measure_latency else 0)
	set_readahead(1 if readahead else 0)
	jifpager_reset()

	if cold:
		dropcache()

	if second_app is not None:
		run(f"sudo -E {JRUN} {CONFIG} {extra_flags} --jif -rk -- {second_app}.jm {second_app}_itrees_ord_reorder.jif >> {output_log}_itrees_jif_k_second_app 2>&1")

	run(f"sudo -E {JRUN} {CONFIG} {extra_flags} --jif -rk -- {image}.jm {image}_itrees_ord{"_reorder" if reorder else ""}.jif >> {output_log}_itrees_jif_k  2>&1")

	stats = open("/sys/kernel/jif_pager/stats")
	stats = json.loads(stats.readlines()[0])
	print(dict(stats))

	total_pages = stats["sync_pages_read"] + stats["async_pages_read"]
	total_faults = stats["minor_faults"] + stats["major_faults"] + stats["pre_minor_faults"] + stats["pre_major_faults"]

	if total_pages > 0:
		overread = float(total_faults / total_pages) * 100.0
		batch_size = total_pages / stats["sync_readaheads"]

		stats["percent_touched"] = overread
		stats["batch_size"] = batch_size

	stats["readahead"] = readahead
	stats["prefault"] = prefault
	stats["cold"] = cold

	key = image.split("/")[-1]
	stats['key'] = key
	with open(f"{output_log}_itrees_jif_k_kstats", "a") as f:
		f.write(json.dumps(stats))
		f.write('\n')

def set_readahead(val):
	run(f"echo {val} | sudo tee /sys/kernel/jif_pager/readahead")

def set_fault_around(val):
	run(f"echo {val} | sudo tee /sys/kernel/jif_pager/fault_around")

def set_prefault(val):
	run(f"echo {val} | sudo tee /sys/kernel/jif_pager/prefault")

def set_prefault_minor(val):
	run(f"echo {val} | sudo tee /sys/kernel/jif_pager/prefault_minor")

def set_measure_latency(val):
	run(f"echo {val} | sudo tee /sys/kernel/jif_pager/measure_latency")

def jifpager_reset():
	run("echo 1 | sudo tee /sys/kernel/jif_pager/reset")

def generate_images(cmd, name, logname, stop_count = 1, extra_flags = ""):
	if ENABLE_ELF_BASELINE:
		snapshot_elf(cmd, name, logname, extra_flags, stop_count)
	snapshot_jif(cmd, name, logname, extra_flags, stop_count)
	process_itree(f"{CHROOT_DIR}/{name}" if USE_CHROOT else name, logname)

	# generate ord with tracer
	restore_jif(name, f"{logname}_buildord", extra_flags=f" {extra_flags} --stackswitch --mem-trace --mem-trace-out {name}.ord")

	process_fault_order(f"{CHROOT_DIR}/{name}" if USE_CHROOT else name, logname)

def get_baseline(cmd, edir):
	run(f"DONTSTOP=1 {cmd} >> {edir}/restore_images_linux 2>&1")

def dropcache():
	for i in range(DROPCACHE):
		if i > 0: time.sleep(5)
		run("echo 3 | sudo tee /proc/sys/vm/drop_caches")

RESTORE_CONFIG_SET = [
	("linux", "Linux warm"),
	("elf", "ELF"),
	("itrees_jif", "JIF\nuserspace"),
	("itrees_jif_k", "JIF\nkernel"),
	("reorder_itrees_jif_k", "JIF\nkernel\nReorder"),
	("prefault_itrees_jif_k", "JIF\nkernel\n(w/ prefetch)"),
	("prefault_minor_itrees_jif_k", "JIF\nkernel\n(w/ prefetch)\nprefault minor"),
	("prefault_reorder_itrees_jif_k", "JIF\nkernel\n(w/ prefetch)\n(w/ reorder)"),
	("prefault_reorder_minor_itrees_jif_k", "JIF\nkernel\n(w/ prefetch)\n(w/ reorder)\nprefault minor"),

	# Not commonly used ones
	("reorder_itrees_jif", "JIF\nuserspace\nReordered"),
	("nora_itrees_jif_k", "JIF\nkernel\nNo RA"),
	("nora_reorder_itrees_jif_k", "JIF\nkernel\nNo RA\nReorder"),
	("nora_prefault_itrees_jif_k", "JIF\nkernel\n(w/ prefetch)\nNo RA"),
	("prefault_reorder_simple_itrees_jif_k", "JIF\nkernel\n(w/ prefetch)\n(w/ reorder)\n(float op)"),
	("prefault_reorder_self_itrees_jif_k", "JIF\nkernel\n(w/ prefetch)\n(w/ reorder)\n(self)"),
	("reorder_simple_itrees_jif_k", "JIF\nkernel\n(w/ reorder)\n(float op)"),
	("reorder_self_itrees_jif_k", "JIF\nkernel\n(w/ reorder)\n(self)"),
	("nora_prefault_reorder_itrees_jif_k", "JIF\nkernel\n(w/ prefetch)\n(w/ reorder)\nNoRA"),
]

def restore_image(name, logname, extra_flags=""):
	if ENABLE_ELF_BASELINE:
		dropcache()
		restore_elf(name, logname, extra_flags)
	if ENABLE_JIF_USERSPACE_BASELINE:
		dropcache()
		restore_itrees_jif(name, logname, extra_flags)

	# use the reorder file with userspace restore (increases VMA setup costs)
	if False:
		dropcache()
		restore_itrees_jif(name, f"{logname}_reorder", extra_flags, reorder=True)

	if jifpager_installed():
		if DO_KERNEL_NO_PREFETCH_EXP:

			# Kernel module restore (no prefetching)
			jifpager_restore_itrees(name, logname, extra_flags=extra_flags, measure_latency=False, readahead=True, prefault=False, cold=True, reorder=False)

			# Kernel module restore using reorder file, with/without readahead
			if False:
				jifpager_restore_itrees(name, f"{logname}_reorder", extra_flags=extra_flags, measure_latency=False, readahead=True, prefault=False, cold=True, reorder=True)
				jifpager_restore_itrees(name, f"{logname}_nora", extra_flags=extra_flags, measure_latency=False, readahead=False, prefault=False, cold=True, reorder=False)
				jifpager_restore_itrees(name, f"{logname}_nora_reorder", extra_flags=extra_flags, measure_latency=False, readahead=False, prefault=False, cold=True, reorder=True)

		if DO_KERNEL_PREFETCH_EXP:
			# Prefault pages
			jifpager_restore_itrees(name, f"{logname}_prefault", extra_flags=extra_flags, measure_latency=False, readahead=True, prefault=True, cold=True, reorder=False)
			jifpager_restore_itrees(name, f"{logname}_prefault_minor", extra_flags=extra_flags, minor=True, measure_latency=False, readahead=True, prefault=True, cold=True, reorder=False)
		if DO_KERNEL_PREFETCH_REORDER_EXP:
			# Prefault pages with reordered contiguous data section
			jifpager_restore_itrees(name, f"{logname}_prefault_reorder", extra_flags=extra_flags, measure_latency=False, readahead=True, prefault=True, cold=True, reorder=True)
			jifpager_restore_itrees(name, f"{logname}_prefault_reorder_minor", extra_flags=extra_flags, minor=True, measure_latency=False, readahead=True, prefault=True, cold=True, reorder=True)

		if False:
			# try warming things with one image restore before the main one
			for tag, f in [("simple", "/tmp/float_operation"), ("self", name)]:
				jifpager_restore_itrees(name, f"{logname}_prefault_reorder_{tag}", extra_flags=extra_flags, measure_latency=False, readahead=True, prefault=True, cold=True, reorder=True, second_app=f)
				jifpager_restore_itrees(name, f"{logname}_reorder_{tag}", extra_flags=extra_flags, measure_latency=False, readahead=True, prefault=False, cold=True, reorder=True, second_app=f)

def do_image(edir, cmd, name, eflags, stop_count = 1):
	try:
		if REDO_SNAPSHOT:
			generate_images(cmd, f"/tmp/{name}", f"{edir}/generate_images", stop_count=stop_count, extra_flags=eflags)
		restore_image(f"/tmp/{name}", f"{edir}/restore_images", extra_flags=eflags)
	except:
		raise
		pass

def get_fbench_times(edir):
	eflags = ""
	if USE_CHROOT:
		eflags += f" --chroot={CHROOT_DIR}  --cache_linux_fs "
	for fn in FBENCH:
		cmd = f"{ROOT_DIR}/bin/venv/bin/python3 {ROOT_DIR}/build/junction/samples/snapshots/python/function_bench/run.py {fn}"
		if LINUX_BASELINE: get_baseline(cmd, edir)
		do_image(edir, cmd, fn, eflags)
	for name, cmd in RESIZERS:
		for image, path in IMAGES:
			stop_count = 2 if "java" in name else 1
			nm = f"{name}_resizer_{image}"
			fullcmd = f"{cmd} {path} {nm}"
			do_image(edir, fullcmd, nm, eflags, stop_count = stop_count)
			if LINUX_BASELINE: get_baseline(fullcmd, edir)

def get_one_log(name):
	try:
		with open(name) as x:
			dat = x.read().splitlines()
	except:
		return {}

	progs = {}
	prev_restore = None
	for l in dat:
		if "DATA  " not in l:
			if "restore time" in l:
				prev_restore = l
			continue
		lx = l.split("DATA  ")[-1].strip()
		xx = json.loads(lx)
		assert xx['program'] not in progs, xx

		if prev_restore:
			l = prev_restore.split("restore time")[1].split()
			xx["metadata_restore"] = int(l[2])
			xx["data_restore"] = int(l[4])
			xx["fs_restore"] = int(l[6])
			prev_restore = None

		progs[xx["program"]] = xx

	return progs

def getstats(d):
	return {
		'cold_first_iter': d["cold"][0],
		'data_restore': d.get("data_restore"),
		'first_iter': d['warmup'][0],
		'warm_iter': d['warmup'][-1],
		'metadata_restore': d.get("metadata_restore"),
		'fs_restore': d.get("fs_restore"),
	}

def get_kstats(fn, data, expn):
	try:
		with open(fn, "r") as f:
			for line in f.readlines():
				jx = json.loads(line)
				data[jx['key']][expn]['jifpager_stats_ns'] = jx
	except:
		pass

def parse_fbench_times(edir):
	from pprint import pprint

	out = defaultdict(dict)

	for tag, name in RESTORE_CONFIG_SET:
		for prog, d in get_one_log(f"{edir}/restore_images_{tag}").items():
			out[prog][tag] = getstats(d)
		get_kstats(f"{edir}/restore_images_{tag}_kstats", out, tag)

	pprint(out)
	return out

def plot_workloads(edir, data):
	workloads = list(data.keys())
	num_workloads = len(workloads)
	fig, axes = plt.subplots(num_workloads, 1, figsize=(10, 5 * num_workloads))

	if num_workloads == 1:
		axes = [axes]

	def get_colors(cat):
		return {
			'function': 'tab:blue',
			'metadata': 'tab:orange',
			'fs': 'tab:green',
			'data': 'tab:red',
			'slowdown': 'tab:blue',
		}.get(cat)

	for ax, workload in zip(axes, workloads):
		categories = data[workload]

		# jifpager_stats_ns = categories['jifpager_stats_ns']

		# how do I get needed throughput? in pages/s
		# for x in jifpager_stats_ns:
		# 	print(x)
		# if not jifpager_stats_ns.get("readahead", False):
		# 	no_readahead = jifpager_stats_ns

		# should only be major faults but just in case
		# total_pages = no_readahead["major_faults"] + no_readahead["minor_faults"]
		# read_latency = no_readahead["average_sync_read_latency"]

		# ideal_throughput = int((total_pages / first_iter) * 1000000 * 4096)
		# bytes per nanosecond
		# actual_throughput = int((4096 / read_latency) * 1000000000)

		# print(f"{workload} ideal throughput = {ideal_throughput / 1024 ** 2}MB/s")
		# print(f"{workload} actual throughput = {actual_throughput / 1024 ** 2}MB/s")

		WARM_ITER = list(categories.items())[0][1]["warm_iter"]
		stack1 = [
			(WARM_ITER, 'function')
		]

		SLOWDOWN = False
		FUNCTION_ONLY = False
		SUM = False
		stacks = []
		if not SLOWDOWN:
			stacks.append((stack1, "Warm", None))

		for exp, ename in RESTORE_CONFIG_SET:
			if exp not in categories:
				continue
			jpstats = None
			if 'jifpager_stats_ns' in categories[exp]:
				jpstats = categories[exp]['jifpager_stats_ns']
			stacks.append(([
				(categories[exp]["cold_first_iter"], "function"),
				(categories[exp]["metadata_restore"], "metadata"),
				(categories[exp]["fs_restore"], "fs"),
				(categories[exp]["data_restore"], "data"),
			], ename, jpstats))

		seen = set()

		def get_lbl(label):
			if label in seen: return None
			seen.add(label)
			return {
				'function': 'Function',
				'metadata': 'Cereal restore',
				'fs': 'MemFS restore',
				'data': 'VMA restore'
			}.get(label, label)

		for stack, label, jpstat in stacks:
			bottom = 0
			if SUM or SLOWDOWN:
				if FUNCTION_ONLY:
					sm = next(l[0] for l in stack if l[1] == "function")
				else:
					sm = sum(l[0] for l in stack if l[0] is not None)
				if SLOWDOWN:
					sm /= WARM_ITER
				ax.bar(label, sm, color=get_colors('slowdown'))
			else:
				for val, category in stack:
					if val is None:
						continue
					ax.bar(label, val, bottom=bottom, color=get_colors(category), label=get_lbl(category))
					bottom += val
			if jpstat is None:
				continue
			txt = f"Major: {jpstat['major_faults']}"
			txt += f"\n  Pre-major: {jpstat['pre_major_faults']}"
			txt += f"\n Minor: {jpstat['minor_faults']}"
			txt += f"\n  Pre-minor: {jpstat['pre_minor_faults']}"
			ax.text(
                x=label,
                y=sm / 2 if SLOWDOWN or SUM else stack[0][0] / 2,
                s=txt,
                ha='center',
                va='center',
                color='white',
                fontsize=8,
                fontweight='bold'
            )

		ax.set_ylabel("Microseconds" if not SLOWDOWN else "Slowdown")
		# ax.set_yscale('log')
		if workload in FBENCH:
			workload = "function_bench: " + workload
		if SLOWDOWN:
			workload += f" - {WARM_ITER / 1000} ms warm iter"
		ax.set_title(workload)
		ax.legend()

	plt.tight_layout()
	plt.savefig(f'{edir}/graph.pdf', bbox_inches='tight')

def main():
	name = ""
	name = f"run.{datetime.now().strftime('%Y%m%d%H%M%S')}{name}"
	os.system(f"mkdir {name}")
	get_fbench_times(name)
	data = parse_fbench_times(name)
	plot_workloads(name, data)

if __name__ == '__main__':
	if len(sys.argv) > 1:
		for d in sys.argv[1:]:
			plot_workloads(d, parse_fbench_times(d))
	else:
		run_iok()
		setup_chroot()
		main()
