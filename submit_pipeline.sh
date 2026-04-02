#!/bin/bash
#SBATCH --job-name=tartandrive_pipeline
#SBATCH --account=def-beltrame
#SBATCH --time=24:00:00                 # adjust per number of tars (100 GB = ~2–4 h each)
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8              # bag processing benefits from multiple cores
#SBATCH --mem=32G                      # extraction + processing headroom
#SBATCH --output=%x_%j.out
#SBATCH --error=%x_%j.err
# Optional: run on a node with local SSD for faster I/O during extraction


module load StdEnv/2023 python/3.10 gcc/12.3 opencv/4.10.0


SCRATCH_DIR="$SCRATCH/tartandrive"
OUTPUT_DIR="${SCRATCH_DIR}/processed"
WORKDIR="${HOME}/projects/def-beltrame/vnm_datasets/tartan_drive"          

TARS_DIR="${HOME}/projects/def-beltrame/vnm_datasets/processed_datasets" 

mkdir -p "$SCRATCH_DIR"
mkdir -p "$OUTPUT_DIR"
mkdir -p "$TARS_DIR"    


echo "=== Disk usage at start ==="
df -h "$SCRATCH_DIR"
echo ""

cd "$WORKDIR"
source tartan_venv/bin/activate

python tartandrive_pipeline.py \
    --scratch-dir    "$SCRATCH_DIR"    \
    --output-dir     "$OUTPUT_DIR"     \
    --file-list      azfiles.txt       \
    --process-script process_bags.py   \
    --dest-path "$TARS_DIR"            \
    --dataset-name   tartan_drive      \
    --sample-rate    4.0               \
    --num-trajs      -1                \
    --timeout        3000              \
    --max-retries    5                 \
    --min-free-gb    250               \
    # --no-cleanup   # uncomment to keep raws for debugging

EXIT_CODE=$?

# ─── Show disk state at end ───────────────────────────────────────────────────
echo ""
echo "=== Disk usage at end ==="
df -h "$SCRATCH_DIR"

exit $EXIT_CODE
