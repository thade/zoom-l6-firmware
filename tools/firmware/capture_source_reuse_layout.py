"""Explicit one-boot reuse proposal inside the original loaded DSP source.

DSP must finish expanding before code replaces its compressed bytes. These
constants are only selected by the explicit source-reuse experiment and its
isolated marker diagnostic.
"""
CODE_START=0x800a9688 # Leave 640 bytes for the live loader at 800a9408.
GLOBALS_START=0x800b0a00
GLOBALS_LIMIT=0x800b1180
CODE_INTERVAL=(CODE_START,GLOBALS_START)
