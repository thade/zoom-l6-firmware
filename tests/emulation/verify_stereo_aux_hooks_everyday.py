#!/usr/bin/env python3
"""The stereo AUX hook groups on the clean everyday build: verify_stereo_aux_hooks.py in 'everyday' mode."""
import runpy,sys
from pathlib import Path
sys.argv=[sys.argv[0],'everyday']
runpy.run_path(str(Path(__file__).with_name('verify_stereo_aux_hooks.py')),run_name='__main__')
