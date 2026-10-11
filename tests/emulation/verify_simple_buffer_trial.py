#!/usr/bin/env python3
"""Exact experiment 23 image (2.731 s history, 16-KiB writes, priority 10): the take-trial suite in 'buffer' mode."""
import runpy,sys
from pathlib import Path
sys.argv=[sys.argv[0],'buffer']
runpy.run_path(str(Path(__file__).with_name('verify_simple_take.py')),run_name='__main__')
