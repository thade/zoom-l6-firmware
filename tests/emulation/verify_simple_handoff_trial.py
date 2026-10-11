#!/usr/bin/env python3
"""Exact experiment 21 image (capture plus pad handoff): the take-trial suite in 'handoff' mode."""
import runpy,sys
from pathlib import Path
sys.argv=[sys.argv[0],'handoff']
runpy.run_path(str(Path(__file__).with_name('verify_simple_take.py')),run_name='__main__')
