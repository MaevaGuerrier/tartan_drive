'''
Author: Wenshan Wang
Date: 2024-09-06

This file contains the download class, which downloads the data from Azure to the local machine.
'''
# General imports.
import os
import time

from colorama import Fore, Style

import boto3
from botocore import UNSIGNED
from botocore.client import Config

# Local imports.
from os.path import isdir, isfile, join
import argparse

def print_error(msg):
    print(Fore.RED + msg + Style.RESET_ALL)

def print_warn(msg):
    print(Fore.YELLOW + msg + Style.RESET_ALL)

def print_highlight(msg):
    print(Fore.GREEN + msg + Style.RESET_ALL)


class AirLabDownloader(object):
    def __init__(self, bucket_name='tartandrive', timeout=600, max_retries=5) -> None:
        endpoint_url = "https://airlab-cloud.andrew.cmu.edu:8080/swift/v1/AUTH_ac8533a83cff4d48bc8c608ad222d330"

        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            config=Config(
                signature_version=UNSIGNED,
                connect_timeout=timeout,
                read_timeout=timeout,
                retries={'max_attempts': max_retries, 'mode': 'adaptive'}
            )
        )
        self.bucket_name = bucket_name
        self.max_retries = max_retries

    def download_with_retry(self, source_file_name, target_file_name):
        """Download a file with retry logic"""
        retry_count = 0
        backoff_time = 5  # Initial backoff time in seconds

        # Ensure target directory exists (preserves path structure like boto3 version)
        target_dir = os.path.dirname(target_file_name)
        if target_dir and not os.path.exists(target_dir):
            os.makedirs(target_dir)

        while retry_count < self.max_retries:
            try:
                print(f"  Downloading {source_file_name} from {self.bucket_name}... (Attempt {retry_count + 1}/{self.max_retries})")
                resp = self.client.get_object(Bucket=self.bucket_name, Key=source_file_name)

                with open(target_file_name, "wb") as f:
                    for chunk in resp["Body"].iter_chunks(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)

                print(f"  Successfully downloaded {source_file_name} to {target_file_name}!")
                return True

            except Exception as e:
                retry_count += 1
                if retry_count >= self.max_retries:
                    print_error(f"  Failed to download {source_file_name} after {self.max_retries} attempts.")
                    print_error(f"  Error: {str(e)}")
                    # Remove partial file if it exists
                    if isfile(target_file_name):
                        os.remove(target_file_name)
                    return False
                else:
                    wait_time = backoff_time * (2 ** (retry_count - 1))  # Exponential backoff
                    print_warn(f"  Download failed: {str(e)}")
                    print_warn(f"  Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)

        return False

    def download(self, filelist, destination_path, skip_existing=True):
        target_filelist = []
        failed_files = []

        for idx, source_file_name in enumerate(filelist):
            # Preserve directory structure (matching boto3 version behaviour)
            target_file_name = join(destination_path, source_file_name)

            print(f'\n[{idx + 1}/{len(filelist)}] Processing {source_file_name}')

            if isfile(target_file_name):
                if skip_existing:
                    print_warn(f'  File {target_file_name} already exists, skipping...')
                    target_filelist.append(target_file_name)
                    continue
                else:
                    print_error(f'  Error: Target file {target_file_name} already exists.')
                    return False, None

            success = self.download_with_retry(source_file_name, target_file_name)

            if success:
                target_filelist.append(target_file_name)
            else:
                failed_files.append(source_file_name)

        if failed_files:
            print_error(f"\n\nFailed to download {len(failed_files)} files:")
            for f in failed_files:
                print_error(f"  - {f}")
            print_warn("\nYou can re-run the script to retry downloading failed files.")
            return False, target_filelist

        return True, target_filelist


class TartandriveDownloader():
    def __init__(self, timeout=600, max_retries=5):
        super().__init__()
        self.downloader = AirLabDownloader(timeout=timeout, max_retries=max_retries)

    def unzip_files(self, zipfilelist, target_folder):
        print_warn('Note unzipping will overwrite existing files ...')
        for zipfile in zipfilelist:
            if not isfile(zipfile) or (not zipfile.endswith('.zip')):
                print_error("The zip file is missing {}".format(zipfile))
                return False
            print('  Unzipping {} ...'.format(zipfile))
            cmd = 'unzip -q -o ' + zipfile + ' -d ' + target_folder
            os.system(cmd)
        print_highlight("Unzipping Completed! ")

    def download(self, target_path, unzip=False, skip_existing=True, **kwargs):
        """
        Download files with resume capability.

        Args:
            target_path: Directory to save downloaded files
            unzip: Whether to unzip files after download
            skip_existing: Skip files that already exist (enables resume)
        """
        if not isdir(target_path):
            os.makedirs(target_path)

        with open('azfiles.txt', 'r') as f:
            lines = f.readlines()

        zipfilelist = [ll.strip() for ll in lines if ll.strip()]

        print_highlight(f"Starting download of {len(zipfilelist)} files...")
        suc, targetfilelist = self.downloader.download(zipfilelist, target_path, skip_existing=skip_existing)

        if suc:
            print_highlight("\n\nDownload completed! Enjoy using Tartandrive!")
        else:
            print_warn("\n\nDownload completed with some failures. Re-run the script to retry failed downloads.")

        if unzip and targetfilelist:
            self.unzip_files(targetfilelist, target_path)

        return suc


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='TartanAir')

    parser.add_argument('--download-dir', default='./tartan_drive_datasets',
                        help='root directory for downloaded files')
    parser.add_argument('--timeout', type=int, default=3000,
                        help='connection timeout in seconds (default: 3000)')
    parser.add_argument('--max-retries', type=int, default=5,
                        help='maximum number of retry attempts (default: 5)')
    parser.add_argument('--no-skip-existing', action='store_true',
                        help='do not skip existing files (default: skip existing)')

    args = parser.parse_args()

    downloader = TartandriveDownloader(timeout=args.timeout, max_retries=args.max_retries)
    downloader.download(
        args.download_dir,
        skip_existing=not args.no_skip_existing
    )