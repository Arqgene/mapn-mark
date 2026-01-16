TOOL_KNOWLEDGE = {
    "filtlong": {
        "purpose": "Read quality filtering",
        "explanation": (
            "Filtlong filters Nanopore reads based on quality and length. "
            "It removes low-quality reads that negatively affect genome assembly."
        ),
        "input": "Raw FASTQ reads",
        "output": "High-quality filtered FASTQ reads"
    },

    "flye": {
        "purpose": "De novo genome assembly",
        "explanation": (
            "Flye assembles long Nanopore reads into contigs using repeat graphs. "
            "It is optimized for noisy long-read sequencing data."
        ),
        "input": "Filtered FASTQ reads",
        "output": "Draft genome assembly (FASTA)"
    },

    "minimap2": {
        "purpose": "Read-to-assembly alignment",
        "explanation": (
            "Minimap2 aligns long reads back to the assembled genome to detect errors "
            "and guide polishing."
        ),
        "input": "Assembly FASTA + reads",
        "output": "PAF alignment file"
    },

    "racon": {
        "purpose": "Genome polishing",
        "explanation": (
            "Racon corrects sequencing errors in the genome assembly using aligned reads, "
            "improving base-level accuracy."
        ),
        "input": "Reads + alignments + assembly",
        "output": "Polished genome FASTA"
    },

    "prokka": {
        "purpose": "Genome annotation",
        "explanation": (
            "Prokka identifies genes, rRNAs, tRNAs, and functional annotations in "
            "prokaryotic genomes."
        ),
        "input": "Polished genome FASTA",
        "output": "Annotated genome files (GFF, GBK, FAA, FFN)"
    },

    "quast": {
        "purpose": "Assembly quality assessment",
        "explanation": (
            "QUAST evaluates genome assembly quality using metrics such as N50, "
            "GC content, and contig statistics."
        ),
        "input": "Genome FASTA",
        "output": "Assembly quality reports"
    }
}
