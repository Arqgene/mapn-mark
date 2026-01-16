
import os
import subprocess
import sys

def to_wsl_path(win_path: str) -> str:
    if not win_path: return win_path
    drive, rest = os.path.splitdrive(os.path.abspath(win_path))
    if drive:
        drive_letter = drive[0].lower()
        path = rest.replace("\\", "/")
        return f"/mnt/{drive_letter}{path}"
    return win_path.replace("\\", "/")

cwd = os.getcwd()
blast_db_path = os.path.join(cwd, "blast_db", "reference")
query_path = os.path.join(cwd, "blast_db", "reference.fasta") # Use reference as query

wsl_db = to_wsl_path(blast_db_path)
wsl_query = to_wsl_path(query_path)

cmd = [
    "wsl",
    "blastn",
    "-query", wsl_query,
    "-db", wsl_db,
    "-outfmt", "6 qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore",
    "-max_target_seqs", "10",
    "-num_threads", "4"
]

print(f"Running command: {cmd}")

try:
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
except subprocess.CalledProcessError as e:
    print("ERROR:", e)
    print("STDOUT:", e.stdout)
    print("STDERR:", e.stderr)
