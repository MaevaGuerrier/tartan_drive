"""
TartanDrive Full Pipeline for Compute Canada Scratch

Flow per tar file:
  1. Download .tar from S3 (AirLabDownloader)
  2. Extract → discover .bag files (unknown folder structure)
  3. Run bag processing script → ./processed_output/
  4. Delete extracted tar + raw bags (free scratch space)
  5. After all tars done: zip processed output → transfer to home node

Usage:
  python tartandrive_pipeline.py \
    --scratch-dir    /scratch/$USER/tartandrive \
    --output-dir     /scratch/$USER/tartandrive/processed \
    --dest-path    where tars file should be stored \
    --dataset-name   tartan_drive \
    --sample-rate    4.0
"""

import os
import glob
import time
import shutil
import tarfile
import argparse
import subprocess
from pathlib import Path

from colorama import Fore, Style


# ─── Logging helpers ──────────────────────────────────────────────────────────

def log(msg):       print(f"[PIPELINE] {msg}")
def log_ok(msg):    print(Fore.GREEN  + f"[OK]  {msg}" + Style.RESET_ALL)
def log_warn(msg):  print(Fore.YELLOW + f"[WARN] {msg}" + Style.RESET_ALL)
def log_err(msg):   print(Fore.RED    + f"[ERR] {msg}" + Style.RESET_ALL)


# ─── Disk space check ─────────────────────────────────────────────────────────

def free_gb(path):
    """Return free space in GB for the filesystem containing `path`."""
    stat = shutil.disk_usage(path)
    return stat.free / (1024 ** 3)

def require_space(path, needed_gb, label=""):
    available = free_gb(path)
    if available < needed_gb:
        log_err(f"Not enough space{' for ' + label if label else ''}. "
                f"Need {needed_gb:.1f} GB, have {available:.1f} GB on {path}")
        return False
    log(f"Disk OK: {available:.1f} GB free on {path} (need {needed_gb:.1f} GB{' for ' + label if label else ''})")
    return True


# ─── Download ─────────────────────────────────────────────────────────────────

def download_tar(tar_name, scratch_dir, timeout, max_retries):
    """
    Use AirLabDownloader to fetch one tar file.
    Returns path to the downloaded tar, or None on failure.
    """
    # Import here so the script is importable even without boto3 at edit time
    from downloader import AirLabDownloader   # same folder as this script

    downloader = AirLabDownloader(timeout=timeout, max_retries=max_retries)
    success, downloaded = downloader.download(
        filelist=[tar_name],
        destination_path=scratch_dir,
        skip_existing=True,
    )

    if not success or not downloaded:
        log_err(f"Download failed for {tar_name}")
        return None

    local_path = os.path.join(scratch_dir, tar_name)
    if not os.path.isfile(local_path):
        log_err(f"Expected file not found after download: {local_path}")
        return None

    size_gb = os.path.getsize(local_path) / (1024 ** 3)
    log_ok(f"Downloaded {tar_name} ({size_gb:.1f} GB)")
    return local_path


# ─── Extract ──────────────────────────────────────────────────────────────────

def extract_tar(tar_path, extract_dir):
    """
    Extract a tar file into extract_dir.
    Returns extract_dir on success, None on failure.
    Handles .tar, .tar.gz, .tar.bz2, .tgz automatically.
    """
    os.makedirs(extract_dir, exist_ok=True)
    log(f"Extracting {tar_path} → {extract_dir} ...")

    try:
        # Use system tar for speed (streaming, no full-load into memory)
        cmd = ["tar", "--extract", "--file", tar_path,
               "--directory", extract_dir,
               "--checkpoint=10000",            # print a dot every ~5 GB
               "--checkpoint-action=echo=#%u"]
        result = subprocess.run(cmd, check=True)
        log_ok(f"Extraction complete: {extract_dir}")
        return extract_dir
    except subprocess.CalledProcessError as e:
        log_err(f"Extraction failed: {e}")
        return None


def find_bag_files(root_dir):
    """Recursively find all .bag files under root_dir."""
    bags = list(Path(root_dir).rglob("*.bag"))
    log(f"Found {len(bags)} .bag file(s) under {root_dir}")
    for b in bags:
        log(f"  {b}")
    return [str(b) for b in bags]


# ─── Process bags ─────────────────────────────────────────────────────────────

def run_bag_processing(input_dir, output_dir, dataset_name, sample_rate,
                       num_trajs=-1, process_script="process_bags.py"):
    """
    Call the bag processing script as a subprocess.
    Returns True on success.
    """
    os.makedirs(output_dir, exist_ok=True)

    cmd = [
        "python", process_script,
        "--dataset-name", dataset_name,
        "--input-dir",    input_dir,
        "--output-dir",   output_dir,
        "--sample-rate",  str(sample_rate),
        "--num-trajs",    str(num_trajs),
    ]

    log(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd)

    if result.returncode != 0:
        log_err(f"Bag processing exited with code {result.returncode}")
        return False

    log_ok("Bag processing complete.")
    return True


# ─── Cleanup ──────────────────────────────────────────────────────────────────

def safe_remove(path, label=""):
    """Delete a file or directory tree, logging the result."""
    try:
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
        else:
            log_warn(f"Nothing to remove at {path}")
            return
        log(f"Removed {label or path}")
    except Exception as e:
        log_warn(f"Could not remove {label or path}: {e}")


# ─── Zip ──────────────────────────────────────────────────────────────────────

def zip_output(output_dir, zip_path):
    """
    Create a gzipped tarball of output_dir at zip_path.
    Returns True on success.
    """
    log(f"Zipping {output_dir} → {zip_path} ...")
    cmd = [
        "tar", "--create", "--gzip",
        "--file", zip_path,
        "--directory", str(Path(output_dir).parent),
        Path(output_dir).name,
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        log_err(f"Zip failed (exit {result.returncode})")
        return False
    size_gb = os.path.getsize(zip_path) / (1024 ** 3)
    log_ok(f"Archive created: {zip_path} ({size_gb:.2f} GB)")
    return True


# ─── Transfer ─────────────────────────────────────────────────────────────────

def copy_to_dest(zip_path, dest_path):
    """
    Copy the zip file to a local destination path on the same machine.
    Returns True on success.
    """
    if not dest_path:
        log_warn("No --dest-path specified — skipping copy.")
        return True

    dest_path = os.path.expandvars(os.path.expanduser(dest_path))
    os.makedirs(dest_path, exist_ok=True)

    dest_file = os.path.join(dest_path, os.path.basename(zip_path))
    log(f"Copying {zip_path} → {dest_file} ...")
    try:
        shutil.copy2(zip_path, dest_file)
        size_gb = os.path.getsize(dest_file) / (1024 ** 3)
        log_ok(f"Copy complete: {dest_file} ({size_gb:.2f} GB)")
        return True
    except Exception as e:
        log_err(f"Copy failed: {e}")
        return False


# ─── Main pipeline ────────────────────────────────────────────────────────────

def load_file_list(path="azfiles.txt"):
    with open(path) as f:
        return [l.strip() for l in f if l.strip()]


def main(args):
    scratch      = args.scratch_dir
    output_dir   = args.output_dir
    extract_base = os.path.join(scratch, "extracted")  # temp extraction dir

    os.makedirs(scratch,      exist_ok=True)
    os.makedirs(output_dir,   exist_ok=True)
    os.makedirs(extract_base, exist_ok=True)

    tar_files = load_file_list(args.file_list)
    log(f"Pipeline starting — {len(tar_files)} tar file(s) to process")
    log(f"  Scratch:    {scratch}")
    log(f"  Output:     {output_dir}")
    log(f"  Script:     {args.process_script}")
    log(f"  Dataset:    {args.dataset_name}")

    failed_tars = []

    for idx, tar_name in enumerate(tar_files):
        print()
        log(f"━━━ [{idx+1}/{len(tar_files)}] {tar_name} ━━━")

        # ── Estimate space needed: download (100 GB) + extraction (~same) ──
        if not require_space(scratch, needed_gb=args.min_free_gb, label=tar_name):
            log_err("Aborting to protect scratch quota.")
            break

        # ── 1. Download ────────────────────────────────────────────────────
        tar_path = os.path.join(scratch, tar_name)
        if os.path.isfile(tar_path):
            log_warn(f"Tar already downloaded, reusing: {tar_path}")
        else:
            tar_path = download_tar(tar_name, scratch,
                                    timeout=args.timeout,
                                    max_retries=args.max_retries)
            if tar_path is None:
                failed_tars.append(tar_name)
                continue

        # ── 2. Extract ─────────────────────────────────────────────────────
        # Use a per-tar subdirectory so extractions don't collide
        tar_stem     = Path(tar_name).stem.replace(".tar", "")
        extract_dir  = os.path.join(extract_base, tar_stem)

        if os.path.isdir(extract_dir) and any(Path(extract_dir).rglob("*.bag")):
            log_warn(f"Extraction dir already has bags, reusing: {extract_dir}")
        else:
            safe_remove(extract_dir, label=f"stale extract dir {extract_dir}")
            result = extract_tar(tar_path, extract_dir)
            if result is None:
                failed_tars.append(tar_name)
                safe_remove(tar_path, label="failed tar")
                continue

        # ── 3. Discover bags ───────────────────────────────────────────────
        bag_files = find_bag_files(extract_dir)
        if not bag_files:
            log_warn(f"No .bag files found in {extract_dir}. Skipping.")
            failed_tars.append(tar_name)
            safe_remove(tar_path,   label="tar (no bags)")
            safe_remove(extract_dir, label="extract dir (no bags)")
            continue

        # The bag processing script takes a directory; give it the highest
        # common ancestor that contains all bags.
        bag_input_dir = extract_dir   # recursive walk in the script handles nesting

        # ── 4. Process bags ────────────────────────────────────────────────
        ok = run_bag_processing(
            input_dir     = bag_input_dir,
            output_dir    = output_dir,
            dataset_name  = args.dataset_name,
            sample_rate   = args.sample_rate,
            num_trajs     = args.num_trajs,
            process_script= args.process_script,
        )
        if not ok:
            log_warn(f"Bag processing had errors for {tar_name} — keeping output so far.")

        # ── 5. Cleanup heavy files ─────────────────────────────────────────
        if args.cleanup:
            safe_remove(extract_dir, label=f"extracted dir for {tar_stem}")
            safe_remove(tar_path,    label=f"tar {tar_name}")
        else:
            log_warn("--no-cleanup set: raw tar and extracted files kept.")

    # ── 6. Zip processed output ────────────────────────────────────────────
    print()
    log("━━━ All tars processed — zipping output ━━━")
    zip_path = os.path.join(scratch, "tartandrive_processed_output.tar.gz")
    zipped   = zip_output(output_dir, zip_path)

    # ── 7. Copy zip to destination ─────────────────────────────────────────
    if zipped:
        copy_to_dest(zip_path, args.dest_path)

    # ── Summary ────────────────────────────────────────────────────────────
    print()
    if failed_tars:
        log_warn(f"Completed with {len(failed_tars)} failure(s):")
        for f in failed_tars:
            log_warn(f"  ✗ {f}")
        log_warn("Re-run the script to retry; already-processed tars will be skipped.")
    else:
        log_ok("Pipeline completed successfully!")


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TartanDrive end-to-end pipeline")

    # Paths
    parser.add_argument("--scratch-dir",    default="/scratch/$USER/tartandrive",
                        help="Root scratch directory for downloads and extraction")
    parser.add_argument("--output-dir",     default="/scratch/$USER/tartandrive_processed",
                        help="Where processed trajectory folders (images + pkl) are saved")
    parser.add_argument("--file-list",      default="azfiles.txt",
                        help="Text file listing tar filenames to download (one per line)")
    parser.add_argument("--process-script", default="process_bags.py",
                        help="Path to the bag processing Python script")

    # Transfer
    parser.add_argument("--dest-path", required=True,
                        help="Local destination directory for the final zip file, e.g. ~/projects/tartandrive/")

    # Bag processing args
    parser.add_argument("--dataset-name",  default="tartan_drive",
                        help="Dataset name key in tartan_bags_config.yaml")
    parser.add_argument("--sample-rate",   type=float, default=4.0,
                        help="Sampling rate in Hz for bag processing")
    parser.add_argument("--num-trajs",     type=int,   default=-1,
                        help="Max trajectories per bag (-1 = all)")

    # Download args
    parser.add_argument("--timeout",       type=int,   default=3000)
    parser.add_argument("--max-retries",   type=int,   default=5)

    # Safety
    parser.add_argument("--min-free-gb",   type=float, default=250.0,
                        help="Minimum free scratch space (GB) required before each download")
    parser.add_argument("--no-cleanup",    dest="cleanup", action="store_false",
                        help="Keep raw tars and extracted dirs after processing")
    parser.set_defaults(cleanup=True)

    args = parser.parse_args()

    # Expand $USER in paths
    for attr in ("scratch_dir", "output_dir"):
        setattr(args, attr, os.path.expandvars(getattr(args, attr)))

    main(args)