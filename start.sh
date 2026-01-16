#!/bin/bash
eval "$(conda shell.bash hook)"
conda activate pipeline
python main.py
