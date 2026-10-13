#!/usr/bin/env python3
"""Every master-reference group on the clean everyday build: verify_master_ref.py in 'everyday' mode."""
import runpy,sys
from pathlib import Path
sys.argv=[sys.argv[0],'everyday']
runpy.run_path(str(Path(__file__).with_name('verify_master_ref.py')),run_name='__main__')
