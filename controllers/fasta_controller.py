import difflib
from flask import render_template, request, flash

# -------------------------------------------------
# FASTA PARSER
# -------------------------------------------------
def parse_fasta(file_content: str) -> dict:
    """
    Parse FASTA content into {header: sequence}
    """
    sequences = {}
    header = None
    buffer = []

    for line in file_content.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith(">"):
            if header:
                sequences[header] = "".join(buffer)
            header = line[1:].strip()
            buffer = []
        else:
            buffer.append(line.upper())

    if header:
        sequences[header] = "".join(buffer)

    return sequences


# -------------------------------------------------
# SEQUENCE COMPARISON WITH HIGHLIGHTING
# -------------------------------------------------
def compare_sequences(seq1: str, seq2: str) -> str:
    """
    Highlight:
      - Match: same regions
      - Mismatch: replaced regions
      - Delete: unique to seq1
      - Insert: present only in seq2
    """
    matcher = difflib.SequenceMatcher(None, seq1, seq2)
    html = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        s1 = seq1[i1:i2]
        s2 = seq2[j1:j2]

        if tag == "equal":
            html.append(f'<span class="match">{s1}</span>')

        elif tag == "replace":
            html.append(
                f'<span class="mismatch" title="→ {s2}">{s1}</span>'
            )

        elif tag == "delete":
            html.append(
                f'<span class="delete" title="Unique to File 1">{s1}</span>'
            )

        elif tag == "insert":
            html.append(
                f'<span class="insert" title="Only in File 2">{s2}</span>'
            )

    return "".join(html)


# -------------------------------------------------
# ROUTES
# -------------------------------------------------
def index():
    return render_template("fasta_compare.html")


def compare():
    if "file1" not in request.files or "file2" not in request.files:
        flash("Please upload both FASTA files.", "error")
        return render_template("fasta_compare.html")

    file1 = request.files["file1"]
    file2 = request.files["file2"]

    if not file1.filename or not file2.filename:
        flash("No file selected.", "error")
        return render_template("fasta_compare.html")

    try:
        seqs1 = parse_fasta(file1.read().decode("utf-8"))
        seqs2 = parse_fasta(file2.read().decode("utf-8"))

        ids1, ids2 = set(seqs1), set(seqs2)

        common = sorted(ids1 & ids2)
        unique1 = sorted(ids1 - ids2)
        unique2 = sorted(ids2 - ids1)

        results = []

        for gid in common:
            diff_html = compare_sequences(seqs1[gid], seqs2[gid])
            results.append({
                "id": gid,
                "status": "Common",
                "diff": diff_html,
                "len1": len(seqs1[gid]),
                "len2": len(seqs2[gid])
            })

        for gid in unique1:
            results.append({
                "id": gid,
                "status": "Unique to File 1",
                "diff": seqs1[gid],
                "len1": len(seqs1[gid]),
                "len2": 0
            })

        for gid in unique2:
            results.append({
                "id": gid,
                "status": "Unique to File 2",
                "diff": seqs2[gid],
                "len1": 0,
                "len2": len(seqs2[gid])
            })

        return render_template(
            "fasta_result.html",
            results=results,
            filename1=file1.filename,
            filename2=file2.filename
        )

    except Exception as e:
        flash(f"Processing error: {e}", "error")
        return render_template("fasta_compare.html")
