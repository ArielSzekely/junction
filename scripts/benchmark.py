#!/usr/bin/python3

import stat
import os
import atexit
import sys
from datetime import datetime
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

USE_CHROOT = True

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
		return stat.S_ISCHR(os.stat("/dev/jif_pager").st_mode)
	except:
		return False

def snapshot_elf(cmd, output_image, output_log, extra_flags = "", stop_count = 1):
	run(f"sudo -E {JRUN} {CONFIG} {extra_flags} -S {stop_count} --snapshot-prefix {output_image} -- {cmd} 2>&1 >> {output_log}_snapelf")

def snapshot_jif(cmd, output_image, output_log, extra_flags = "", stop_count = 1):
	run(f"sudo -E {JRUN} {CONFIG} {extra_flags} --jif -S {stop_count} --snapshot-prefix {output_image} -- {cmd} 2>&1 >> {output_log}_snapjif")

def restore_elf(image, output_log, extra_flags = ""):
	run(f"sudo -E {JRUN} {CONFIG} {extra_flags} -r -- {image}.metadata {image}.elf 2>&1 >> {output_log}_elf")

def process_itree(output_image, output_log):
	run(f"{BUILD_DIR}/jiftool {output_image}.jif {output_image}_itrees.jif build-itrees 2>&1 >> {output_log}_builditree")

def process_fault_order(output_image, output_log):
	# add ordering to jif
	run(f"{BUILD_DIR}/jiftool {output_image}_itrees.jif {output_image}_itrees_ord.jif add-ord {output_image}.ord")

def restore_jif(image, output_log, extra_flags = ""):
	run(f"sudo -E {JRUN} {CONFIG} {extra_flags} --jif -r -- {image}.jm {image}.jif 2>&1 >> {output_log}_jif")

def restore_itrees_jif(image, output_log, extra_flags = ""):
	run(f"sudo -E {JRUN} {CONFIG} {extra_flags} --jif -r -- {image}.jm {image}_itrees.jif 2>&1 >> {output_log}_itrees_jif")

def jifpager_restore_itrees(image, output_log, cold=False, fault_around=True, measure_latency=False, prefault=False, readahead=True, extra_flags = ""):
	set_fault_around(1 if fault_around else 0)
	set_prefault(1 if prefault else 0)
	set_measure_latency(1 if measure_latency else 0)
	set_readahead(1 if readahead else 0)
	jifpager_reset()

	if cold:
		dropcache()

	run(f"sudo -E {JRUN} {CONFIG} {extra_flags} --jif -rk -- {image}.jm {image}_itrees_ord.jif 2>&1 >> {output_log}_itrees_jif_k")

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
	with open(f"{output_log}_kstats", "a") as f:
		f.write(json.dumps(stats))
		f.write('\n')

def set_readahead(val):
	run(f"echo {val} | sudo tee /sys/kernel/jif_pager/readahead")

def set_fault_around(val):
	run(f"echo {val} | sudo tee /sys/kernel/jif_pager/fault_around")

def set_prefault(val):
	run(f"echo {val} | sudo tee /sys/kernel/jif_pager/prefault")

def set_measure_latency(val):
	run(f"echo {val} | sudo tee /sys/kernel/jif_pager/measure_latency")

def jifpager_reset():
	run("echo 1 | sudo tee /sys/kernel/jif_pager/reset")

def generate_images(cmd, name, logname, stop_count = 1, extra_flags = ""):
	snapshot_elf(cmd, name, logname, extra_flags, stop_count)
	snapshot_jif(cmd, name, logname, extra_flags, stop_count)
	process_itree(f"{CHROOT_DIR}/{name}" if USE_CHROOT else name, logname)

	# generate ord with tracer
	restore_jif(name, f"{logname}_buildord", extra_flags=f" {extra_flags} --stackswitch --mem-trace --mem-trace-out {name}.ord")

	process_fault_order(f"{CHROOT_DIR}/{name}" if USE_CHROOT else name, logname)

def dropcache():
	for i in range(5):
		run("echo 3 | sudo tee /proc/sys/vm/drop_caches")
		time.sleep(10)

def restore_image(name, logname, extra_flags=""):
	dropcache()
	restore_elf(name, logname, extra_flags)
	dropcache()
	restore_itrees_jif(name, logname, extra_flags)

	if jifpager_installed():
		jifpager_restore_itrees(name, logname, extra_flags=extra_flags, measure_latency=False, readahead=False, prefault=True, cold=True, fault_around=False)

def do_image(edir, cmd, name, eflags, stop_count = 1):
	generate_images(cmd, f"/tmp/{name}", f"{edir}/generate_images", stop_count=stop_count, extra_flags=eflags)
	restore_image(f"/tmp/{name}", f"{edir}/restore_images", extra_flags=eflags)

def get_fbench_times(edir):
	eflags = ""
	if USE_CHROOT:
		eflags += f" --chroot={CHROOT_DIR}  --cache_linux_fs "
	for fn in FBENCH:
		cmd = f"{ROOT_DIR}/bin/venv/bin/python3 {ROOT_DIR}/build/junction/samples/snapshots/python/function_bench/run.py {fn}"
		do_image(edir, cmd, fn, eflags)
	for name, cmd in RESIZERS:
		for image, path in IMAGES:
			stop_count = 2 if "java" in name else 1
			nm = f"{name}_resizer_{image}"
			do_image(edir, f"{cmd} {path} {nm}", nm, eflags, stop_count = stop_count)

def get_one_log(name):
	try:
		with open(name) as x:
			dat = x.read().splitlines()
	except:
		return None

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

def parse_fbench_times(edir):
	from pprint import pprint

	out = {}
	for prog, d in get_one_log(f"{edir}/restore_images_elf").items():
		out[prog] = {
			'first_iter': d['warmup'][0],
			'warm_iter': d['warmup'][-1],
			'metadata_restore': d["metadata_restore"],
			'elf_cold_first_iter': d["cold"][0],
			'elf_data_restore': d["data_restore"],
			'fs_restore': d["fs_restore"],
		}

	with open(f"{edir}/restore_images_kstats", "r") as f:
		for line in f.readlines():
			jx = json.loads(line)
			print(out)
			out[jx['key']]['jifpager_stats_ns'] = jx

	for prog, d in get_one_log(f"{edir}/restore_images_itrees_jif").items():
		out[prog]['jif_cold_first_iter'] = d["cold"][0]
		out[prog]['jif_data_restore'] = d["data_restore"]

	for prog, d in get_one_log(f"{edir}/restore_images_itrees_jif_k").items():
		out[prog]['jif_k_cold_first_iter'] = d["cold"][0]
		out[prog]['jif_k_data_restore'] = d["data_restore"]

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

		stack1 = [
			('warm_iter', 'function')
		]

		stack2 = [
			("elf_cold_first_iter", "function"),
			("metadata_restore", "metadata"),
			("fs_restore", "fs"),
			("elf_data_restore", "data"),
		]

		stack3 = [
			("jif_cold_first_iter", "function"),
			("metadata_restore", "metadata"),
			("fs_restore", "fs"),
			("jif_data_restore", "data"),
		]

		stack4 = [
			("jif_k_cold_first_iter", "function"),
			("metadata_restore", "metadata"),
			("fs_restore", "fs"),
			("jif_k_data_restore", "data"),
		]

		stacks = [
			(stack1, "Warm"),
			(stack2, "ELF restore"),
			(stack3, "JIF restore (userspace)"),
			(stack4, "JIF kernel restore\n(w/ prefetch)"),
		]


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

		for stack, label in stacks:
			bottom = 0
			for component, category in stack:
				ax.bar(label, categories[component], bottom=bottom, color=get_colors(category), label=get_lbl(category))
				bottom += categories[component]

		ax.set_ylabel("Microseconds")
		# ax.set_yscale('log')
		if workload in FBENCH:
			workload = "function_bench: " + workload
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
