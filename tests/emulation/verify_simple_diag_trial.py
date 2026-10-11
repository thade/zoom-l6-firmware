#!/usr/bin/env python3
"""Exact experiment 22 image (handoff plus service diagnostics): the take-trial suite in 'diag' mode."""
import runpy,sys
from pathlib import Path
sys.argv=[sys.argv[0],'diag']
runpy.run_path(str(Path(__file__).with_name('verify_simple_take.py')),run_name='__main__')
